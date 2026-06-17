import socket
import os
from loguru import logger


def check_internal_network() -> bool:
    """사내망 접속 여부를 확인합니다."""
    subnet = os.getenv("INTERNAL_SUBNET", "")
    if not subnet:
        logger.warning("INTERNAL_SUBNET 환경변수가 설정되지 않았습니다. 네트워크 검증을 건너뜁니다.")
        return True

    try:
        hostname = socket.gethostbyname(socket.gethostname())
        if hostname.startswith(subnet):
            logger.info(f"사내망 접속 확인됨: {hostname}")
            return True
        else:
            logger.error(f"사내망 외부에서 실행 시도됨: {hostname} (허용 대역: {subnet}.*)")
            return False
    except Exception as e:
        logger.error(f"네트워크 확인 중 오류 발생: {e}")
        return False


def require_internal_network() -> None:
    """사내망이 아니면 RuntimeError를 발생시킵니다."""
    if not check_internal_network():
        raise RuntimeError("이 프로그램은 사내망에서만 실행할 수 있습니다. VPN 또는 사내 네트워크에 연결해 주세요.")
