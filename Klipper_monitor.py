#!/usr/bin/env python3
import time
from Klipper_server import PrinterMonitor, init_db


def main():
    init_db()
    monitor = PrinterMonitor()
    initial_status = monitor.get_printer_status()
    if initial_status:
        monitor.last_state = initial_status['print_stats']['state']
        print(f"初始打印机状态: {monitor.last_state}")
    print("🚀 打印机监控服务已启动，开始监控...")
    monitor.monitor_loop()


if __name__ == "__main__":
    main()