"""
定时调度器 - Cron调度 + 守护进程模式
支持：自动触发圆桌会议、单一实例锁、日志记录
"""
import os
import sys
import json
import time
import signal
import logging
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional, Callable

import yaml


class Scheduler:
    """汉堡王自治系统的定时调度器"""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.base_dir = Path(__file__).parent.parent
        self.config = self._load_config(config_path)
        self.logger = self._setup_logger()
        self.running = False
        self.current_job: Optional[threading.Thread] = None
        self.lock_file = self.base_dir / ".scheduler.lock"
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        full_path = self.base_dir / config_path
        if not full_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {full_path}")
        with open(full_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        log_dir = self.base_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        
        logger = logging.getLogger("burger_king.scheduler")
        logger.setLevel(logging.INFO)
        
        # 文件处理器
        fh = logging.FileHandler(
            log_dir / f"burger_king_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8"
        )
        fh.setLevel(logging.INFO)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        
        logger.addHandler(fh)
        logger.addHandler(ch)
        return logger

    def _signal_handler(self, signum, frame):
        """信号处理"""
        self.logger.info(f"收到信号 {signum}，准备退出...")
        self.running = False

    def _acquire_lock(self) -> bool:
        """获取运行锁，防止重复实例"""
        try:
            if self.lock_file.exists():
                # 检查旧锁是否过期（超过1小时）
                mtime = self.lock_file.stat().st_mtime
                if time.time() - mtime < 3600:
                    self.logger.warning("检测到已有实例运行，退出")
                    return False
                else:
                    self.logger.warning("旧锁已过期，删除并重新获取")
                    self.lock_file.unlink()
            
            # 写入锁文件
            with open(self.lock_file, "w") as f:
                f.write(json.dumps({
                    "pid": os.getpid(),
                    "start_time": datetime.now().isoformat(),
                    "hostname": os.uname().nodename if hasattr(os, 'uname') else "windows"
                }))
            return True
        except Exception as e:
            self.logger.error(f"获取锁失败: {e}")
            return False

    def _release_lock(self):
        """释放锁"""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass

    def _is_work_hours(self) -> bool:
        """检查是否在工作时间"""
        now = datetime.now()
        
        # 检查是否周末
        if now.weekday() >= 5:  # 0=周一, 5=周六, 6=周日
            return False
        
        # 检查是否在8:00-18:00
        current_time = now.time()
        start = dtime(8, 0)
        end = dtime(18, 0)
        
        return start <= current_time <= end

    def _run_roundtable(self, topic: str = "auto", turns: int = 10):
        """执行一轮圆桌会议"""
        from core.roundtables import Roundtable
        
        self.logger.info(f"开始执行圆桌会议: 主题={topic}, 轮数={turns}")
        
        try:
            rt = Roundtable(self.config, self.logger)
            result = rt.run(topic=topic, turns=turns)
            self.logger.info(f"圆桌会议完成: 结果={result.get('status', 'unknown')}")
            return result
        except Exception as e:
            self.logger.error(f"圆桌会议执行失败: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def _job_worker(self, topic: str = "auto", turns: int = 10):
        """工作线程"""
        self.logger.info(f"[Job] 开始执行，topic={topic}")
        result = self._run_roundtable(topic=topic, turns=turns)
        self.logger.info(f"[Job] 执行完成: {result.get('status')}")
        self.current_job = None

    def trigger(self, topic: str = "auto", turns: int = 10):
        """手动触发一次圆桌会议"""
        if self.current_job and self.current_job.is_alive():
            self.logger.warning("上一次圆桌会议仍在执行中，跳过")
            return {"status": "skipped", "reason": "previous_job_running"}
        
        thread = threading.Thread(
            target=self._job_worker,
            args=(topic, turns),
            daemon=True
        )
        self.current_job = thread
        thread.start()
        return {"status": "triggered"}

    def start(self):
        """启动调度器（守护进程模式）"""
        if not self._acquire_lock():
            sys.exit(1)
        
        self.running = True
        self.logger.info("=" * 50)
        self.logger.info("🍔 汉堡王自治系统调度器启动")
        self.logger.info(f"工作时段: 工作日 8:00-18:00")
        self.logger.info(f"触发间隔: 每30分钟")
        self.logger.info("=" * 50)
        
        last_trigger_time = 0
        
        while self.running:
            now = datetime.now()
            
            # 检查是否在工作时间
            if self._is_work_hours():
                current_min = now.hour * 60 + now.minute
                
                # 每30分钟触发一次（:00 和 :30）
                if now.minute in [0, 30]:
                    if current_min != last_trigger_time:
                        last_trigger_time = current_min
                        self.trigger(topic="auto", turns=self.config["scheduler"]["max_turns"])
            
            # 每分钟检查一次
            time.sleep(60)
        
        self._release_lock()
        self.logger.info("调度器已退出")

    def status(self) -> dict:
        """获取调度器状态"""
        return {
            "running": self.running,
            "current_job_alive": self.current_job.is_alive() if self.current_job else False,
            "lock_exists": self.lock_file.exists(),
            "is_work_hours": self._is_work_hours()
        }


if __name__ == "__main__":
    scheduler = Scheduler()
    scheduler.start()
