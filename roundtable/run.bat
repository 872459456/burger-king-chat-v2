@echo off
REM 圆桌会议启动脚本
REM 用法：
REM   run.bat single   - 执行一轮圆桌（供Cron调用）
REM   run.bat continuous - 持续运行（手动测试用）

cd /d D:\works\Project\burger-king-chat-v2\roundtable

if "%1"=="single" (
    python roundtable.py
) else if "%1"=="continuous" (
    python roundtable.py --continuous
) else (
    echo 用法: run.bat [single^|continuous]
)
