import serial
import logging
import time
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def read_barcode(port, baudrate=115200, timeout=0.1, packet_timeout=0.15):
    """
    packet_timeout: 多久没收到新数据就认为一次完整条码结束（秒）
    """
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )
        logger.info(f"串口 {port} 打开成功，波特率 {baudrate}，等待扫码...")
    except serial.SerialException as e:
        logger.error(f"无法打开串口 {port}: {e}")
        return

    buffer = b''  # 原始字节缓冲区
    last_recv = time.time()
    try:
        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                buffer += data
                last_recv = time.time()

                # 处理完整行（以 \n 结尾）
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    line = line.rstrip(b'\r').strip()
                    if line:
                        try:
                            text = line.decode('utf-8')
                        except UnicodeDecodeError:
                            text = line.decode('gbk', errors='replace')
                        logger.info(f"扫描到条码: {text}")

            else:
                # 没有新数据，检查是否已经等待足够长时间来输出无换行的条码
                if buffer and (time.time() - last_recv) > packet_timeout:
                    line = buffer.strip()
                    if line:
                        try:
                            text = line.decode('utf-8')
                        except UnicodeDecodeError:
                            text = line.decode('gbk', errors='replace')
                        logger.info(f"扫描到条码: {text}")
                    buffer = b''
                time.sleep(0.02)
    except KeyboardInterrupt:
        logger.info("用户终止监听")
    finally:
        ser.close()
        logger.info(f"串口 {port} 已关闭")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="扫码器数据接收日志工具")
    parser.add_argument("port", help="串口号，如 COM14 或 /dev/ttyUSB0")
    parser.add_argument("-b", "--baudrate", type=int, default=115200,
                        help="波特率（默认 115200）")
    args = parser.parse_args()

    read_barcode(args.port, args.baudrate)