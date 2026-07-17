#!/usr/bin/env python3
"""
VNStock CLI Installer - Text-based installer for headless environments
Perfect for: Google Colab, Linux VPS, SSH sessions, Docker containers

Features:
- Beautiful ASCII art interface
- Progress bars and animations
- Color-coded output
- Interactive prompts
- Non-interactive mode for automation
- Simple API key management
- Bilingual support (Vietnamese/English)

Author: vnstock-lab
License: MIT
"""

__version__ = "3.0.2"

import sys
import os
import platform
import subprocess
import shutil
import time
import argparse
import json
import hashlib
import socket
import uuid
import requests
from pathlib import Path
from datetime import datetime

# Core dependencies (synchronized with GUI config.py)
# Includes all required packages for vnstock functionality

# Requirements configuration
# Now loaded dynamically from hosted file where possible
REQUIREMENTS_URL = "https://vnstocks.com/files/requirements.txt"
VNSTOCKS_INDEX_URL = 'https://vnstocks.com/api/simple'

# Core dependencies (synchronized with GUI config.py)
# Includes all required packages for vnstock functionality
# Note: These serve as fallback if remote requirements cannot be fetched
# Fallback dependencies (used only if REQUIREMENTS_URL is unreachable)
# In normal operation, requirements are loaded from REQUIREMENTS_URL
# These lists only contain critical packages needed to bootstrap installation
REQUIRED_DEPENDENCIES_FALLBACK = [
    # Critical system packages (must be upgraded first to avoid conflicts)
    'typing_extensions>=4.6.0',  # Required by pydantic_core (Sentinel class)
    'vnstock',
    'vnai',
    'vnii',
    'requests',
    'pandas',
    'numpy',
]

# Colab-specific fallback (lightweight, install only missing packages)
COLAB_REQUIREMENTS_FALLBACK = [
    # Critical system packages
    'typing_extensions>=4.6.0',  # Required by pydantic_core
    'vnstock',
    'vnai',
    'vnii',
]

# Critical system dependencies (auto-installed if missing)
# These are required by vnstock-installer.py to function
CRITICAL_DEPENDENCIES = {
    'typing_extensions': 'typing_extensions',  # Import name
    'vnai': 'vnai',
    'vnii': 'vnii',
    'requests': 'requests',
}

# ==================== Configuration Module ====================

# User Configuration Paths
HOME_DIR = Path.home()
CONFIG_DIR = HOME_DIR / ".vnstock"
API_KEY_FILE = CONFIG_DIR / "api_key.json"
USER_INFO_FILE = CONFIG_DIR / "user.json"
DEVICE_ID_FILE = CONFIG_DIR / "device.id"
LOG_FILE = CONFIG_DIR / "cli_installer.log"

# Ensure config directory exists
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def save_api_key(api_key: str) -> bool:
    """Save API key to ~/.vnstock/api_key.json"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        api_key_data = {'api_key': api_key}
        
        with open(API_KEY_FILE, 'w') as f:
            json.dump(api_key_data, f, indent=2)
        
        return True
    except Exception:
        return False


def load_api_key() -> str:
    """Load API key from ~/.vnstock/api_key.json or user.json"""
    try:
        if API_KEY_FILE.exists():
            with open(API_KEY_FILE, 'r') as f:
                data = json.load(f)
                return data.get('api_key', '')
        
        if USER_INFO_FILE.exists():
            with open(USER_INFO_FILE, 'r') as f:
                data = json.load(f)
                return data.get('api_key', '')
    except Exception:
        pass
    return ""


def save_user_info(user_info: dict) -> bool:
    """Save user info to ~/.vnstock/user.json"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(USER_INFO_FILE, 'w') as f:
            json.dump(user_info, f, indent=2)
        
        return True
    except Exception:
        return False


def get_username_from_api(api_key: str) -> tuple:
    """Get username and email from vnstock API using API key"""
    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        url = 'https://vnstocks.com/api/vnstock/user/profile'
        response = requests.get(
            url,
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            username = user_data.get('username', 'Unknown')
            email = user_data.get('email', 'unknown')
            return username, email
    except Exception:
        pass
    
    return 'Unknown', 'unknown'
# ==================== Utils Module ====================

def get_hardware_uuid() -> str:
    """Get hardware UUID from system"""
    try:
        if platform.system() == "Darwin":
            # macOS: use system_profiler
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split('\n'):
                if 'UUID' in line:
                    return line.split()[-1]
        elif platform.system() == "Linux":
            # Linux: try /etc/machine-id
            try:
                with open('/etc/machine-id', 'r') as f:
                    return f.read().strip()
            except FileNotFoundError:
                pass
        elif platform.system() == "Windows":
            # Windows: use wmi
            try:
                result = subprocess.run(
                    ["wmic", "os", "get", "serialnumber"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                return result.stdout.strip().split('\n')[1]
            except Exception:
                pass
    except Exception:
        pass
    
    # Fallback: generate consistent UUID based on hostname
    return str(uuid.uuid5(
        uuid.NAMESPACE_DNS,
        socket.gethostname()
    ))


def get_mac_address() -> str:
    """Get MAC address"""
    try:
        parts = []
        node = uuid.getnode()
        for elements in range(0, 2*6, 2):
            val = (node >> elements) & 0xff
            parts.append(f'{val:02x}')
        
        mac = ':'.join(parts[::-1])
        return mac
    except Exception:
        return 'unknown'


def generate_device_id(venv_path: str = None) -> dict:
    """Generate unique device identifier using vnai (single source of truth)"""
    device_id = None
    
    # 1. Check environment variable override
    env_device_id = os.environ.get('VNSTOCK_DEVICE_ID')
    if env_device_id:
        device_id = env_device_id
        
    # 2. Check cached device.id file if not found in env
    if not device_id and DEVICE_ID_FILE.exists():
        try:
            device_id = DEVICE_ID_FILE.read_text().strip()
        except Exception:
            pass
            
    # 3. Check user.json if still not found
    if not device_id and USER_INFO_FILE.exists():
        try:
            with open(USER_INFO_FILE, 'r') as f:
                data = json.load(f)
                device_id = data.get('device_id') or data.get('uuid')
        except Exception:
            pass
    
    # Debug logging to file
    log_path = os.path.expanduser('~/vnstock_debug.log')
    with open(log_path, 'a') as f:
        f.write(f"DEBUG: generate_device_id called with venv_path={venv_path}\n")
        f.flush()
    
    # Try direct import first
    try:
        from vnai.scope.profile import inspector
        device_id = inspector.fingerprint()
        with open('/tmp/vnstock_debug.log', 'a') as f:
            f.write(f"DEBUG: Direct import succeeded, device_id={device_id}\n")
    except ImportError as e:
        with open('/tmp/vnstock_debug.log', 'a') as f:
            f.write(f"DEBUG: Direct import failed: {e}\n")
        
        # If import fails and venv_path provided, try subprocess
        subprocess_error = str(e)
        if venv_path:
            try:
                # Find python executable in venv
                if os.name == 'nt':
                    python_exe = os.path.join(venv_path, "Scripts", "python.exe")
                else:
                    python_exe = os.path.join(venv_path, "bin", "python")
                
                if os.path.exists(python_exe):
                    cmd = [
                        python_exe, '-c',
                        'from vnai.scope.profile import inspector; print(inspector.fingerprint())'
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if result.returncode == 0:
                        device_id = result.stdout.strip()
                    else:
                        subprocess_error = f"Subprocess failed with code {result.returncode}. Stderr: {result.stderr.strip()}"
                        with open('/tmp/vnstock_debug.log', 'a') as f:
                            f.write(f"DEBUG: {subprocess_error}\n")
            except Exception as ex:
                subprocess_error = f"Subprocess exception: {ex}"
                pass

    with open('/tmp/vnstock_debug.log', 'a') as f:
        f.write(f"DEBUG: Final device_id={device_id}\n")
        f.flush()
    
    if not device_id:
        raise ImportError(
            f"vnai is required for device identification.\n"
            f"Details: {subprocess_error}\n"
            f"Context: venv_path={venv_path}, current_python={sys.executable}"
        )

    # Cache the device ID for future use/persistence
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DEVICE_ID_FILE.write_text(device_id)
    except Exception:
        pass

    try:
        # Get additional info for compatibility
        try:
            hardware_uuid = get_hardware_uuid()
            mac_address = get_mac_address()
        except:
            hardware_uuid = 'unknown'
            mac_address = 'unknown'
        
        system_info = {
            'platform': platform.platform(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'system': platform.system(),
            'release': platform.release(),
            'node': platform.node(),
            'python_version': (
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            )
        }
        
        return {
            'device_id': device_id,
            'hardware_uuid': hardware_uuid,
            'mac_address': mac_address,
            'system_info': system_info
        }
    except Exception as e:
        raise RuntimeError(
            f"Failed to generate device ID: {e}"
        )


def is_virtual_environment() -> bool:
    """Check if running in virtual environment"""
    return (
        hasattr(sys, "real_prefix") or
        (hasattr(sys, "base_prefix") and
         sys.base_prefix != sys.prefix)
    )


def get_machine_identifier() -> str:
    """Get machine identifier (UUID)"""
    try:
        return str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            socket.gethostname()
        ))
    except Exception:
        return str(uuid.uuid4())


def get_uv_command() -> str:
    """Get UV command path, checking common installation locations
    
    Returns:
        str: Full path to uv executable or 'uv' if in PATH
    """
    # Check common installation locations
    home = os.path.expanduser('~')
    possible_paths = [
        os.path.join(home, '.local', 'bin', 'uv'),  # Standalone installer
        os.path.join(home, '.cargo', 'bin', 'uv'),  # Cargo install
        '/usr/local/bin/uv',                         # System-wide
        '/opt/homebrew/bin/uv',                      # Homebrew (Apple Silicon)
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # Fallback to 'uv' (assume it's in PATH)
    return 'uv'


def ensure_uv_installed(python_executable: str = None) -> bool:
    """Ensure uv is installed"""
    python_exe = python_executable or sys.executable
    
    try:
        # Check if uv is available
        subprocess.run(
            ['uv', '--version'],
            capture_output=True,
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("📦 Installing uv...")
        
        # Try standalone installer first (works with externally-managed Python)
        try:
            result = subprocess.run(
                ['curl', '-LsSf', 'https://astral.sh/uv/install.sh'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                install_result = subprocess.run(
                    ['sh', '-c', result.stdout],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if install_result.returncode == 0:
                    print("✓ uv installed successfully (standalone)")
                    return True
        except Exception:
            pass  # Fall through to pip method
        
        # Fallback: try pip install with --break-system-packages for externally-managed envs
        try:
            result = subprocess.run(
                [python_exe, '-m', 'pip', 'install', '--break-system-packages', 'uv'],
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )
            print("✓ uv installed successfully (pip)")
            return True
        except subprocess.CalledProcessError:
            # If --break-system-packages fails, try without it (older pip versions)
            try:
                result = subprocess.run(
                    [python_exe, '-m', 'pip', 'install', 'uv'],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=60
                )
                print("✓ uv installed successfully (pip)")
                return True
            except subprocess.CalledProcessError as e:
                print(f"✗ uv installation failed: {e.stderr[:200] if e.stderr else 'unknown error'}")
                return False
        except subprocess.TimeoutExpired:
            print("✗ uv installation timeout (60s)")
            return False
        except Exception as e:
            print(f"✗ uv installation error: {e}")
            return False


def create_user_info(
    python_executable: str,
    venv_path: str = None,
    device_info: dict = None,
    api_key: str = None
) -> dict:
    """Create user info dict with system information and user details from API"""
    
    if device_info is None:
        device_info = generate_device_id(venv_path)
    
    # Get real user info from API if api_key provided
    username = "vnstock_cli_installer"
    email = "unknown"
    if api_key:
        username, email = get_username_from_api(api_key)
    
    python_info = {
        'version': (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        'executable': python_executable,
        'is_virtual_env': is_virtual_environment(),
        'virtual_env_path': venv_path
    }
    
    user_info = {
        "user": username,
        "email": email,
        "uuid": get_machine_identifier(),
        "os": platform.system(),
        "os_version": platform.version(),
        "ip": "unknown",
        "cwd": os.getcwd(),
        "python": python_info,
        "time": datetime.now().isoformat(),
        "device_id": device_info['device_id'],
        "hardware_uuid": device_info['hardware_uuid'],
        "mac_address": device_info['mac_address']
    }
    
    return user_info


# Language support
class Lang:
    """Language strings for UI"""
    
    # Detect if Windows (may have encoding issues)
    IS_WINDOWS = platform.system() == 'Windows'
    
    VI = {
        # For Windows: use ASCII-friendly Vietnamese + English notes
        'header_title': 'VNSTOCK - CAI DAT GOI THU VIEN' if IS_WINDOWS else 'VNStock - Cài Đặt Gói Thư Viện',
        'header_subtitle': (
            'Cong cu tai du lieu chung khoan #1 Viet Nam tu API cong khai trong Python'
            if IS_WINDOWS
            else 'Công cụ tải dữ liệu chứng khoán #1 Việt Nam từ API công khai trong Python'
        ),
        'step': 'Buoc' if IS_WINDOWS else 'Bước',
        'detecting_python': 'Phat hien cac phien ban Python' if IS_WINDOWS else 'Phát hiện các phiên bản Python',
        'found': 'Tim thay' if IS_WINDOWS else 'Tìm thấy',
        'selecting_python': 'Chon phien ban Python' if IS_WINDOWS else 'Chọn phiên bản Python',
        'selected': 'Da chon' if IS_WINDOWS else 'Đã chọn',
        'using': 'Dang su dung' if IS_WINDOWS else 'Đang sử dụng',
        'creating_venv': 'Tao moi truong ao' if IS_WINDOWS else 'Tạo môi trường ảo',
        'venv_exists': 'Moi truong ao da ton tai' if IS_WINDOWS else 'Môi trường ảo đã tồn tại',
        'venv_created': 'Moi truong ao da duoc tao' if IS_WINDOWS else 'Môi trường ảo đã được tạo',
        'venv_corrupted': 'Moi truong ao bi hong, dang tao lai...' if IS_WINDOWS else 'Môi trường ảo bị hỏng, đang tạo lại...',
        'venv_removed_failed': 'That bai khi xoa moi truong ao bi hong' if IS_WINDOWS else 'Thất bại khi xóa môi trường ảo bị hỏng',
        'creating': 'Dang tao' if IS_WINDOWS else 'Đang tạo',
        'with': 'voi' if IS_WINDOWS else 'với',
        'installing_deps': 'Cai dat cac goi phu thuoc' if IS_WINDOWS else 'Cài đặt các gói phụ thuộc',
        'installing': 'Dang cai dat' if IS_WINDOWS else 'Đang cài đặt',
        'packages': 'goi' if IS_WINDOWS else 'gói',
        'checking_packages': 'Dang kiem tra cac goi da cai dat...' if IS_WINDOWS else 'Đang kiểm tra các gói đã cài đặt...',
        'all_packages_installed': 'Tat ca cac goi da duoc cai dat, bo qua!' if IS_WINDOWS else 'Tất cả các gói đã được cài đặt, bỏ qua!',
        'need_install_packages': 'Can cai dat' if IS_WINDOWS else 'Cần cài đặt',
        'deps_installed': 'Cac goi phu thuoc da duoc cai dat' if IS_WINDOWS else 'Các gói phụ thuộc đã được cài đặt',
        'api_auth': 'Xac thuc API' if IS_WINDOWS else 'Xác thực API',
        'using_env_key': 'Dang su dung API key tu bien moi truong' if IS_WINDOWS else 'Đang sử dụng API key từ biến môi trường',
        'choose_auth': 'Chon phuong thuc xac thuc:' if IS_WINDOWS else 'Chọn phương thức xác thực:',
        'browser_auth': 'Xac thuc qua Trinh duyet (OAuth)' if IS_WINDOWS else 'Xác thực qua Trình duyệt (OAuth)',
        'manual_entry': 'Nhap API Key thu cong' if IS_WINDOWS else 'Nhập API Key thủ công',
        'select_option': 'Chon (1-2, Enter = 1)' if IS_WINDOWS else 'Chọn (1-2, Enter = 1)',
        'browser_auth_start': 'Bat dau xac thuc qua trinh duyet...' if IS_WINDOWS else 'Bắt đầu xác thực qua trình duyệt...',
        'browser_auth_fail': 'Xac thuc qua trinh duyet that bai, chuyen sang nhap thu cong' if IS_WINDOWS else 'Xác thực qua trình duyệt thất bại, chuyển sang nhập thủ công',
        'enter_api_key': 'Nhap API key' if IS_WINDOWS else 'Nhập API key',
        'api_key_entered': 'Da nhap API key' if IS_WINDOWS else 'Đã nhập API key',
        'no_api_key': 'Chua nhap API key' if IS_WINDOWS else 'Chưa nhập API key',
        'running_installer': 'Chay chuong trinh cai dat VNStock' if IS_WINDOWS else 'Chạy chương trình cài đặt VNStock',
        'running': 'Dang chay' if IS_WINDOWS else 'Đang chạy',
        'installer_success': 'VNStock da duoc cai dat thanh cong!' if IS_WINDOWS else 'VNStock đã được cài đặt thành công!',
        'installer_failed': 'Cai dat that bai voi ma loi' if IS_WINDOWS else 'Cài đặt thất bại với mã lỗi',
        'complete': 'Hoan tat cai dat!' if IS_WINDOWS else 'Hoàn tất cài đặt!',
        'quick_start': 'Huong dan nhanh:' if IS_WINDOWS else 'Hướng dẫn nhanh:',
        'activate_venv': 'Kich hoat moi truong ao:' if IS_WINDOWS else 'Kích hoạt môi trường ảo:',
        'start_using': 'Bat dau su dung VNStock:' if IS_WINDOWS else 'Bắt đầu sử dụng VNStock:',
        'documentation': 'Tai lieu:' if IS_WINDOWS else 'Tài liệu:',
        'log_file': 'File log' if IS_WINDOWS else 'Xem chi tiết log cài đặt tại',
        'available_versions': 'Cac phien ban Python kha dung:' if IS_WINDOWS else 'Các phiên bản Python khả dụng:',
        'select_version': 'Chon phien ban' if IS_WINDOWS else 'Chọn phiên bản',
        'invalid_selection': 'Lua chon khong hop le' if IS_WINDOWS else 'Lựa chọn không hợp lệ',
        'enter_number': 'Vui long nhap so' if IS_WINDOWS else 'Vui lòng nhập số',
        'no_python_found': 'Khong tim thay Python 3.10-3.14!' if IS_WINDOWS else 'Không tìm thấy Python 3.10-3.14!',
        'installer_not_found': 'Khong tim thay chuong trinh cai dat' if IS_WINDOWS else 'Không tìm thấy chương trình cài đặt',
        'failed_create_venv': 'That bai khi tao moi truong ao' if IS_WINDOWS else 'Thất bại khi tạo môi trường ảo',
        'failed_install_deps': 'That bai khi cai dat cac goi phu thuoc' if IS_WINDOWS else 'Thất bại khi cài đặt các gói phụ thuộc',
        'timeout': 'Het thoi gian cho' if IS_WINDOWS else 'Hết thời gian chờ',
        'cancelled': 'Da huy cai dat' if IS_WINDOWS else 'Đã hủy cài đặt',
        'unexpected_error': 'Loi khong mong doi' if IS_WINDOWS else 'Lỗi không mong đợi',
        # Google Drive mount (for API key persistence)
        'drive_mount_required': 'Yeu cau ket noi Google Drive' if IS_WINDOWS else 'Yêu cầu kết nối Google Drive',
        'drive_mount_desc': 'Drive can thiet de luu API key.' if IS_WINDOWS else 'Drive cần thiết để lưu API key.',
        'drive_mount_benefit': 'Ban khong can nhap lai API key sau khi restart!' if IS_WINDOWS else 'Bạn không cần nhập lại API key sau khi restart!',
        'drive_mount_steps': 'Vui long ket noi Google Drive:' if IS_WINDOWS else 'Vui lòng kết nối Google Drive:',
        'drive_mount_step1': '1. Nhan bieu tuong thu muc o thanh ben trai' if IS_WINDOWS else '1. Nhấn biểu tượng thư mục ở thanh bên trái',
        'drive_mount_step2': '2. Nhan nut "Mount Drive"' if IS_WINDOWS else '2. Nhấn nút "Mount Drive"',
        'drive_mount_step3': '3. Cho phep truy cap trong cua so popup' if IS_WINDOWS else '3. Cho phép truy cập trong cửa sổ popup',
        'drive_mount_step4': '4. Doi thong bao "Mounted at /content/drive"' if IS_WINDOWS else '4. Đợi thông báo "Mounted at /content/drive"',
        'drive_already_mounted': 'Google Drive da duoc ket noi' if IS_WINDOWS else 'Google Drive đã được kết nối',
        'drive_mount_success': 'Ket noi Google Drive thanh cong!' if IS_WINDOWS else 'Kết nối Google Drive thành công!',
        'drive_not_found': 'Khong tim thay Google Drive. Vui long ket noi truoc.' if IS_WINDOWS else 'Không tìm thấy Google Drive. Vui lòng kết nối trước.',
        'cannot_proceed_drive': 'Khong the tien hanh ma khong co truy cap Google Drive' if IS_WINDOWS else 'Không thể tiến hành mà không có truy cập Google Drive',
        # Colab environment detection
        'detected_colab': 'Phat hien moi truong Google Colab' if IS_WINDOWS else 'Phát hiện môi trường Google Colab',
        'using_colab_python': 'Dang su dung he thong Python cua Google Colab' if IS_WINDOWS else 'Đang sử dụng hệ thống Python của Google Colab',
        'using_codespaces_python': 'Dang su dung he thong Python cua GitHub Codespaces' if IS_WINDOWS else 'Đang sử dụng hệ thống Python của GitHub Codespaces',
        'colab_temp_install': 'Cai dat vao session hien tai (tam thoi)' if IS_WINDOWS else 'Cài đặt vào session hiện tại (tạm thời)',
        'colab_temp_desc': 'Cac goi se mat sau khi khoi dong lai runtime' if IS_WINDOWS else 'Các gói sẽ mất sau khi khởi động lại runtime',
        'colab_temp_benefit': 'Cai dat nhanh (~1-2 phut)' if IS_WINDOWS else 'Cài đặt nhanh (~1-2 phút)',
        'install_dir_exists': 'Tho muc cai dat da ton tai' if IS_WINDOWS else 'Thư mục cài đặt đã tồn tại',
        'colab_setup_steps': 'Cac buoc cai dat' if IS_WINDOWS else 'Các bước cài đặt',
        'colab_quick_setup_title': 'Cai dat nhanh cho Google Colab' if IS_WINDOWS else 'Cài đặt nhanh cho Google Colab',
        'colab_quick_setup_desc': 'Cai dat thu cong de nhanh hon' if IS_WINDOWS else 'Cài đặt thủ công để nhanh hơn',
        'colab_quick_mode': 'Dung che do nhanh (khuyen nghi)' if IS_WINDOWS else 'Dùng chế độ nhanh (khuyến nghị)',
        'colab_full_mode': 'Cai dat day du (tu dong)' if IS_WINDOWS else 'Cài đặt đầy đủ (tự động)',
        'colab_manual_cmd': 'Chay lenh nay trong cell Colab:' if IS_WINDOWS else 'Chạy lệnh này trong cell Colab:',
        'colab_manual_then': 'Sau do chay installer:' if IS_WINDOWS else 'Sau đó chạy installer:',
        # Validation messages
        'validating': 'Dang xac minh cai dat' if IS_WINDOWS else 'Đang xác minh cài đặt',
        'checking_core': 'Kiem tra phu thuoc co ban...' if IS_WINDOWS else 'Kiểm tra phụ thuộc cơ bản...',
        'checking_vnstock': 'Kiem tra cac module VNStock...' if IS_WINDOWS else 'Kiểm tra các module VNStock...',
        'validation_complete': 'Xac minh hoan tat!' if IS_WINDOWS else 'Xác minh hoàn tất!',
        'missing_core': 'Phu thuoc co ban bi thieu' if IS_WINDOWS else 'Phụ thuộc cơ bản bị thiếu',
        'missing_optional': 'Goi tuy chon bi thieu' if IS_WINDOWS else 'Gói tùy chọn bị thiếu',
        'install_error': 'Cai dat that bai' if IS_WINDOWS else 'Cài đặt thất bại',
        'install_incomplete': 'CAI DAT CHUA HOAN TAT' if IS_WINDOWS else 'CÀI ĐẶT CHƯA HOÀN TẤT',
        'install_warning': 'CAC GOI TACH BIEM BI THIEU' if IS_WINDOWS else 'CÁC GÓI TÙYCHỌN BỊ THIẾU',
        'possible_causes': 'Nguyen nhan co the:' if IS_WINDOWS else 'Nguyên nhân có thể:',
        'install_interrupted': 'Cai dat bi gian doan' if IS_WINDOWS else 'Cài đặt bị gián đoạn',
        'disk_network_issue': 'Trang thai dia hoac mang' if IS_WINDOWS else 'Trạng thái đĩa hoặc mạng',
        'python_incompatible': 'Phien ban Python khong tuong thich' if IS_WINDOWS else 'Phiên bản Python không tương thích',
        'venv_issue': 'Van de moi truong ao' if IS_WINDOWS else 'Vấn đề môi trường ảo',
        'manual_install': 'Cai dat the cong' if IS_WINDOWS else 'Cài đặt thủ công',
        'troubleshooting': 'Huong dan khac phuc su co:' if IS_WINDOWS else 'Hướng dẫn khắc phục sự cố:',
        'continue_without_optional': 'Tiep tuc ma khong co cac goi tuy chon?' if IS_WINDOWS else 'Tiếp tục mà không có các gói tùy chọn?',
        # Validation messages - detailed errors
        'missing_modules': 'Cac module bi thieu:' if IS_WINDOWS else 'Các module bị thiếu:',
        'install_incomplete_modules': 'CAI DAT THAT BAI' if IS_WINDOWS else '❌ CÀI ĐẶT THẤT BẠI',
        'module_install_failed': 'Cac module khong the cai dat' if IS_WINDOWS else 'Các module không thể cài đặt từ installer',
        'check_logs': 'Kiem tra log tai:' if IS_WINDOWS else 'Kiểm tra log tại:',
        'try_pip_install': 'Thu cai dat bang pip:' if IS_WINDOWS else 'Thử cài đặt bằng pip:',
        'check_dependencies': 'Kiem tra cac phu thuoc:' if IS_WINDOWS else 'Kiểm tra các phụ thuộc:',
        'try_reinstall': 'Thu cai dat lai:' if IS_WINDOWS else 'Thử cài đặt lại:',
        'consult_guide': 'Xem huong dan:' if IS_WINDOWS else 'Xem hướng dẫn:',
        'solutions': 'Giai phap:' if IS_WINDOWS else 'Giải pháp:',
        'continue_anyway': 'Tiep tuc? (y/n): ' if IS_WINDOWS else 'Tiếp tục? (y/n): ',
    }
    
    EN = {
        'header_title': 'VNStock Package Installer',
        'header_subtitle': (
            'Vietnam #1 Python Library for Stock API & Analysis'
        ),
        'step': 'Step',
        'detecting_python': 'Detecting Python Versions',
        'found': 'Found',
        'selecting_python': 'Selecting Python Version',
        'selected': 'Selected',
        'using': 'Using',
        'creating_venv': 'Creating Virtual Environment',
        'venv_exists': 'Virtual environment exists',
        'venv_created': 'Virtual environment created',
        'venv_corrupted': 'Virtual environment corrupted, recreating...',
        'venv_removed_failed': 'Failed to remove corrupted virtual environment',
        'creating': 'Creating',
        'with': 'with',
        'installing_deps': 'Installing Dependencies',
        'installing': 'Installing',
        'packages': 'packages',
        'checking_packages': 'Checking installed packages...',
        'all_packages_installed': 'All packages already installed, skipping!',
        'need_install_packages': 'Need to install',
        'deps_installed': 'Dependencies installed',
        'api_auth': 'API Authentication',
        'using_env_key': 'Using API key from environment',
        'choose_auth': 'Choose authentication method:',
        'browser_auth': 'Browser Authentication (OAuth)',
        'manual_entry': 'Manual API Key Entry',
        'select_option': 'Select (1-2, Enter = 1)',
        'browser_auth_start': 'Starting browser authentication...',
        'browser_auth_fail': 'Browser auth failed, falling back to manual',
        'enter_api_key': 'Enter API key',
        'api_key_entered': 'API key entered',
        'no_api_key': 'No API key provided',
        'running_installer': 'Running VNStock Installer',
        'running': 'Running',
        'installer_success': 'VNStock installed successfully!',
        'installer_failed': 'Installer failed with code',
        'complete': 'Installation Complete!',
        'quick_start': 'Quick Start Guide:',
        'activate_venv': 'Activate virtual environment:',
        'start_using': 'Start using VNStock:',
        'documentation': 'Documentation:',
        'log_file': 'Log file',
        'available_versions': 'Available Python versions:',
        'select_version': 'Select version',
        'invalid_selection': 'Invalid selection',
        'enter_number': 'Please enter a number',
        'no_python_found': 'No Python 3.10-3.14 found!',
        'installer_not_found': 'Installer not found',
        'failed_create_venv': 'Failed to create virtual environment',
        'failed_install_deps': 'Failed to install dependencies',
        'timeout': 'Timeout',
        'cancelled': 'Installation cancelled',
        'unexpected_error': 'Unexpected error',
        # Google Drive mount (for API key persistence)
        'drive_mount_required': 'Google Drive Mount Required',
        'drive_mount_desc': 'Drive is needed to store your API key.',
        'drive_mount_benefit': "You won't need to re-enter API key after restart!",
        'drive_mount_steps': 'Please mount Google Drive:',
        'drive_mount_step1': '1. Click the folder icon in the left sidebar',
        'drive_mount_step2': '2. Click the "Mount Drive" button',
        'drive_mount_step3': '3. Authorize access in the popup window',
        'drive_mount_step4': '4. Wait for "Mounted at /content/drive" message',
        'drive_already_mounted': 'Google Drive already mounted',
        'drive_mount_success': 'Google Drive mounted successfully!',
        'drive_not_found': 'Google Drive not found. Please mount it first.',
        'cannot_proceed_drive': 'Cannot proceed without Google Drive access',
        # Colab environment detection
        'detected_colab': 'Detected Google Colab environment',
        'using_colab_python': "Using Google Colab's system Python",
        'using_codespaces_python': "Using GitHub Codespaces' system Python",
        'colab_temp_install': 'Installing to current session (temporary)',
        'colab_temp_desc': 'Packages will be lost after runtime restart',
        'colab_temp_benefit': 'Fast installation (~1-2 minutes)',
        'install_dir_exists': 'Installation directory exists',
        'colab_quick_setup_title': 'Quick Setup for Google Colab',
        'colab_quick_setup_desc': 'Pre-install packages manually for faster setup',
        'colab_quick_mode': 'Use Quick Setup (recommended for Colab)',
        'colab_full_mode': 'Full setup (auto-install packages)',
        'colab_manual_cmd': 'Run this command in a Colab cell:',
        'colab_manual_then': 'Then run the installer:',
        'colab_setup_steps': 'Setup Steps',
        # Validation messages
        'validating': 'Validating installation',
        'checking_core': 'Checking core dependencies...',
        'checking_vnstock': 'Checking VNStock modules...',
        'validation_complete': 'Validation complete!',
        'missing_core': 'Core dependencies missing',
        'missing_optional': 'Optional packages missing',
        'install_error': 'Installation failed',
        'install_incomplete': 'INSTALLATION INCOMPLETE',
        'install_warning': 'OPTIONAL PACKAGES MISSING',
        'possible_causes': 'Possible causes:',
        'install_interrupted': 'Installation was interrupted',
        'disk_network_issue': 'Disk space or network issues',
        'python_incompatible': 'Incompatible Python version',
        'venv_issue': 'Virtual environment issues',
        'manual_install': 'Manual installation',
        'troubleshooting': 'Troubleshooting guide:',
        'continue_without_optional': 'Continue without optional packages?',
        # Validation messages - detailed errors
        'missing_modules': 'Missing vnstock modules:',
        'install_incomplete_modules': '❌ INSTALLATION INCOMPLETE',
        'module_install_failed': (
            'Modules failed to install from installer'
        ),
        'check_logs': 'Check logs at:',
        'try_pip_install': 'Try pip install:',
        'check_dependencies': 'Check dependencies:',
        'try_reinstall': 'Try reinstalling:',
        'consult_guide': 'Troubleshooting guide:',
        'solutions': 'Solutions:',
        'continue_anyway': 'Continue anyway? (y/n): ',
    }
    
    @classmethod
    def get(cls, lang='vi'):
        """Get language dict"""
        return cls.VI if lang == 'vi' else cls.EN


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    
    # Additional colors
    PURPLE = '\033[35m'
    YELLOW = '\033[33m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    GREY = '\033[90m'
    
    # VNStock brand colors (256-color ANSI)
    VNSTOCK_GREEN = '\033[38;5;71m'   # #4CAF50 - Primary (main messages)
    VNSTOCK_PURPLE = '\033[38;5;135m'  # #8C52FF - Secondary (details)
    VNSTOCK_BLUE = '\033[38;5;33m'     # #007BFF - Tertiary (if needed)


class ASCIIArt:
    """ASCII art and decorations"""
    
    LOGO = """
██╗   ██╗███╗   ██╗███████╗████████╗ ██████╗  ██████╗██╗  ██╗
██║   ██║████╗  ██║██╔════╝╚══██╔══╝██╔═══██╗██╔════╝██║ ██╔╝
██║   ██║██╔██╗ ██║███████╗   ██║   ██║   ██║██║     █████╔╝ 
╚██╗ ██╔╝██║╚██╗██║╚════██║   ██║   ██║   ██║██║     ██╔═██╗ 
 ╚████╔╝ ██║ ╚████║███████║   ██║   ╚██████╔╝╚██████╗██║  ██╗
  ╚═══╝  ╚═╝  ╚═══╝╚══════╝   ╚═╝    ╚═════╝  ╚═════╝╚═╝  ╚═╝
"""
    
    HEADER_TEMPLATE = """
╔════════════════════════════════════════════════════════════════════════════════════════════════╗
║{title:^96}║
║{subtitle:^96}║
║{version:^96}║
╚════════════════════════════════════════════════════════════════════════════════════════════════╝
"""
    
    DIVIDER_THICK = "═" * 96
    DIVIDER_THIN = "─" * 96
    DIVIDER_DOT = "·" * 96
    
    SUCCESS = """
    ███████╗██╗   ██╗ ██████╗ ██████╗███████╗███████╗███████╗
    ██╔════╝██║   ██║██╔════╝██╔════╝██╔════╝██╔════╝██╔════╝
    ███████╗██║   ██║██║     ██║     █████╗  ███████╗███████╗
    ╚════██║██║   ██║██║     ██║     ██╔══╝  ╚════██║╚════██║
    ███████║╚██████╔╝╚██████╗╚██████╗███████╗███████║███████║
    ╚══════╝ ╚═════╝  ╚═════╝ ╚═════╝╚══════╝╚══════╝╚══════╝
    """
    
    CHECKMARK = "✓"
    CROSSMARK = "✗"
    ARROW = "→"
    BULLET = "•"
    HOURGLASS = "⏳"
    ROCKET = "🚀"
    PACKAGE = "📦"
    WRENCH = "🔧"
    SPARKLES = "✨"


class ProgressBar:
    """Animated progress bar for CLI"""
    
    def __init__(self, total=100, width=50, prefix="Progress:"):
        self.total = total
        self.width = width
        self.prefix = prefix
        self.current = 0
    
    def update(self, value, suffix=""):
        """Update progress bar"""
        self.current = value
        filled = int(self.width * value / self.total)
        bar = "█" * filled + "░" * (self.width - filled)
        percent = value / self.total * 100
        
        # Clear line and print progress
        print(f"\r{self.prefix} |{bar}| {percent:.1f}% {suffix}", end="")
        sys.stdout.flush()
    
    def finish(self, message="Complete!"):
        """Finish progress bar"""
        self.update(self.total, message)
        print()  # New line


class VNStockCLIInstaller:
    """Main CLI installer class"""
    
    def __init__(self, interactive=True, verbose=False, language='vi', venv_path_arg=None):
        self.interactive = interactive
        self.verbose = verbose
        self.language = language
        self.is_vietnamese = language == 'vi'
        self.lang = Lang.get(language)
        self.python_versions = []
        self.selected_python = None
        self.venv_path = None
        self.venv_type = None  # 'default', 'custom', or 'system'
        self.venv_path_arg = venv_path_arg
        
        # For Colab: Track newly installed packages for backup
        self.newly_installed_packages = set()
        self.packages_before_sponsor = set()  # Snapshot before sponsor install
        
        self.is_colab = self.detect_google_colab()
        self.is_codespaces = self.detect_codespaces()
        self.is_drive_mounted = False
        
        # Set log path (always use ~/.vnstock for temp Colab mode)
        self.log_file = Path.home() / ".vnstock" / "cli_installer.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def detect_google_colab(self):
        """Detect if running in Google Colab environment"""
        try:
            import google.colab
            return True
        except ImportError:
            return False
    
    def detect_codespaces(self):
        """Detect if running in GitHub Codespaces"""
        return os.environ.get('CODESPACES') == 'true' or \
               os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN') is not None
    
    def fetch_requirements_from_url(self, is_colab=False):
        """Fetch requirements from URL, fallback to hardcoded list
        
        Args:
            is_colab: If True, return minimal Colab requirements
            
        Returns:
            list: Requirements list with typing_extensions first
        """
        try:
            response = requests.get(REQUIREMENTS_URL, timeout=10)
            if response.status_code == 200:
                # Parse requirements from URL
                requirements = []
                for line in response.text.strip().split('\n'):
                    line = line.strip()
                    # Skip comments, empty lines, and --extra-index-url lines
                    if line and not line.startswith('#') and not line.startswith('--'):
                        requirements.append(line)
                
                # Ensure typing_extensions is first (critical for pydantic_core)
                typing_ext_reqs = [r for r in requirements if 'typing' in r.lower() and 'extensions' in r.lower()]
                other_reqs = [r for r in requirements if r not in typing_ext_reqs]
                
                # If typing_extensions not in URL, add it
                if not typing_ext_reqs:
                    typing_ext_reqs = ['typing_extensions>=4.6.0']
                
                final_reqs = typing_ext_reqs + other_reqs
                
                self.log(f"Loaded {len(final_reqs)} requirements from URL", "INFO")
                return final_reqs
        except Exception as e:
            self.log(f"Failed to fetch requirements from URL: {e}", "WARNING")
        
        # Fallback to hardcoded lists
        self.log("Using fallback requirements list", "INFO")
        return COLAB_REQUIREMENTS_FALLBACK if is_colab else REQUIRED_DEPENDENCIES_FALLBACK
    
    def mount_google_drive(self):
        """Mount Google Drive for API key persistence
        
        Note: Packages are installed to session temp (fast),
        but API key must be in Drive for persistence across restarts.
        """
        if not self.is_colab:
            return True
        
        drive_path = Path("/content/drive/MyDrive")
        
        # Check if already mounted
        if drive_path.exists():
            self.print_detail(self.lang['drive_already_mounted'])
            # Create .vnstock folder for API key
            vnstock_dir = Path("/content/drive/MyDrive/.vnstock")
            vnstock_dir.mkdir(parents=True, exist_ok=True)
            self.is_drive_mounted = True
            return True
        
        # Drive not mounted - show instructions and offer to skip
        title = f"📁 {self.lang['drive_mount_required']}"
        print(f"\n{Colors.BOLD}{Colors.VNSTOCK_GREEN}{title}{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_DOT)
        print(f"\n{Colors.VNSTOCK_GREEN}"
              f"{self.lang['drive_mount_desc']}{Colors.ENDC}")
        print(f"   {self.lang['drive_mount_benefit']}")
        
        if self.interactive:
            choice = input(f"\n{Colors.CYAN}Bắt đầu kết nối Google Drive? (y/n, Enter=y): {Colors.ENDC}").lower().strip()
            if choice == 'n':
                self.print_warning("Đã bỏ qua kết nối Drive. Cấu hình sẽ không được lưu lại.")
                self.is_drive_mounted = False
                return True
        
        print(f"\n{Colors.BOLD}{Colors.VNSTOCK_GREEN}"
              f"{self.lang['drive_mount_steps']}{Colors.ENDC}")
        print(f"  {self.lang['drive_mount_step1']}")
        print(f"  {self.lang['drive_mount_step2']}")
        print(f"  {self.lang['drive_mount_step3']}")
        print(f"  {self.lang['drive_mount_step4']}")
        
        # Show code to mount Drive
        print(f"\n{Colors.BOLD}{Colors.VNSTOCK_GREEN}"
              f"⚙️ Hoặc chạy lệnh:{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}from google.colab import drive")
        print(f"drive.mount('/content/drive'){Colors.ENDC}")
        print()
        
        print(f"\n{Colors.BOLD}{Colors.FAIL}⚠️  Chạy lại installer "
              f"sau khi mount Drive{Colors.ENDC}")
        print()
        
        return False
    
    def print_header(self):
        """Print beautiful header with version info"""
        subtitle = self.lang['header_subtitle']
        
        # Print logo ASCII
        print(Colors.VNSTOCK_GREEN + ASCIIArt.LOGO + Colors.ENDC)
        # Print subtitle below logo
        print(Colors.VNSTOCK_GREEN + subtitle + Colors.ENDC)
        print(f"{Colors.GREY}CLI Installer v{__version__}{Colors.ENDC}")
        print(Colors.VNSTOCK_GREEN + ASCIIArt.DIVIDER_THICK + Colors.ENDC)
        print()
    
    def log(self, message, level="INFO"):
        """Log message to file"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_file, "a") as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")
    
    def print_step(self, step, total, message_key=None, message=None):
        """Print step header with language support"""
        step_text = f"{self.lang['step']} {step}/{total}"
        
        if message_key:
            msg = self.lang.get(message_key, message_key)
        else:
            msg = message or ""
        
        print(f"\n{Colors.BOLD}[{step_text}] {msg}{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_THIN)
    
    def print_success(self, message):
        """Print success message"""
        print(f"{Colors.OKGREEN}{ASCIIArt.CHECKMARK} {message}{Colors.ENDC}")
    
    def print_error(self, message):
        """Print error message"""
        print(f"{Colors.FAIL}{ASCIIArt.CROSSMARK} {message}{Colors.ENDC}")
    
    def print_warning(self, message):
        """Print warning message"""
        print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")
    
    def print_info(self, message):
        """Print info message"""
        bullet = f"{Colors.VNSTOCK_GREEN}{ASCIIArt.BULLET}"
        print(f"{bullet} {message}{Colors.ENDC}")
    
    def print_detail(self, message):
        """Print detail/secondary message (purple color)"""
        checkmark = f"{Colors.VNSTOCK_PURPLE}{ASCIIArt.CHECKMARK}"
        print(f"{checkmark} {message}{Colors.ENDC}")
    
    def show_colab_quick_setup(self):
        """Offer quick setup option for Colab (manual pip install)"""
        if not self.is_colab:
            return False
        
        print(f"\n{Colors.BOLD}{self.lang['colab_setup_steps']}:{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_DOT)
        
        print(f"\n{Colors.CYAN}Option 1: Quick Setup (⚡ Recommended){Colors.ENDC}")
        print("  ⏱️  Time: ~1 minute | Packages pre-installed")
        
        print(f"\n{Colors.CYAN}Option 2: Full Setup (Auto){Colors.ENDC}")
        print("  ⏱️  Time: ~5-10 minutes | Auto-install all packages")
        
        if self.interactive:
            print()
            choice = input(
                f"{Colors.CYAN}Choose setup mode [1]: {Colors.ENDC}"
            ).strip()
            
            if not choice or choice == '1':
                return True  # Quick setup
            else:
                return False  # Full setup
        else:
            return True  # Default to quick setup in non-interactive
    
    def show_quick_setup_instructions(self):
        """Display quick setup manual install instructions for Colab"""
        print(f"\n{Colors.BOLD}🚀 Manual Setup Instructions:{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_DOT)
        
        print(f"\n{Colors.CYAN}{self.lang['colab_manual_cmd']}{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}{COLAB_MANUAL_INSTALL}{Colors.ENDC}\n")
        
        print(f"{Colors.OKBLUE}Steps:{Colors.ENDC}")
        print("1. Copy the command above")
        print("2. Paste it in a Colab cell (press Shift+Enter)")
        print("3. Wait ~2 minutes for installation to complete")
        print("4. Then come back and run this installer")
        print()
        
        if self.interactive:
            input(f"{Colors.CYAN}Press Enter when ready to continue...{Colors.ENDC}")
    
    def animate_loading(self, message="Loading", duration=2):
        """Show loading animation"""
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        end_time = time.time() + duration
        
        while time.time() < end_time:
            for frame in frames:
                print(f"\r{Colors.CYAN}{frame} {message}...{Colors.ENDC}", end="")
                sys.stdout.flush()
                time.sleep(0.1)
        
        print(f"\r{Colors.OKGREEN}{ASCIIArt.CHECKMARK} {message}... Done!{Colors.ENDC}")
    
    def detect_python_versions(self):
        """Detect and select available Python versions 3.10-3.14"""
        # Note: print_step will be called by select_python_version()
        
        # For hosted environments (Colab/Codespaces), use system Python
        if self.is_colab:
            # Colab uses 'python' (Python 3.x)
            cmd = 'python'
            self.print_info(self.lang['using_colab_python'])
            
            # Get version
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                version_output = result.stdout.strip()
                version_str = version_output.split()[1]
                version_parts = version_str.split('.')
                major = int(version_parts[0])
                minor = int(version_parts[1])
                
                self.python_versions = [{
                    'command': [cmd],
                    'path': [cmd],
                    'version': f"{major}.{minor}",
                    'full_version': version_str,
                    'display': cmd
                }]
                return True
            except Exception as e:
                self.print_error(f"Failed to detect Colab Python: {e}")
                return False
        
        elif self.is_codespaces:
            # Codespaces uses 'python3'
            cmd = 'python3'
            self.print_info(self.lang['using_codespaces_python'])
            
            # Get version
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                version_output = result.stdout.strip()
                version_str = version_output.split()[1]
                version_parts = version_str.split('.')
                major = int(version_parts[0])
                minor = int(version_parts[1])
                
                self.python_versions = [{
                    'command': [cmd],
                    'path': [cmd],
                    'version': f"{major}.{minor}",
                    'full_version': version_str,
                    'display': cmd
                }]
                return True
            except Exception as e:
                self.print_error(f"Failed to detect Codespaces Python: {e}")
                return False
        
        else:
            # Local system: scan for available versions
            found_versions = []
            seen_versions = set()
            
            if platform.system() == 'Windows':
                # Windows: Check registry for Python installations
                # This works even in frozen exe with Windows Store Python
                import winreg
                
                registry_paths = [
                    (winreg.HKEY_CURRENT_USER, r'Software\Python\PythonCore'),
                    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Python\PythonCore'),
                    (winreg.HKEY_CURRENT_USER, r'Software\Python\ContinuumAnalytics'),
                ]
                
                for root_key, subkey_path in registry_paths:
                    try:
                        with winreg.OpenKey(root_key, subkey_path) as key:
                            i = 0
                            while True:
                                try:
                                    version_str = winreg.EnumKey(key, i)
                                    i += 1
                                    
                                    # Parse version
                                    try:
                                        parts = version_str.split('.')
                                        major = int(parts[0])
                                        minor = int(parts[1]) if len(parts) > 1 else 0
                                    except (ValueError, IndexError):
                                        continue
                                    
                                    # Only Python 3.10-3.14
                                    if not (major == 3 and 10 <= minor <= 14):
                                        continue
                                    
                                    # Get executable path
                                    try:
                                        install_path_key = winreg.OpenKey(
                                            key,
                                            version_str + r'\InstallPath'
                                        )
                                        exe_path = winreg.QueryValue(install_path_key, '')
                                        winreg.CloseKey(install_path_key)
                                        
                                        python_exe = Path(exe_path) / 'python.exe'
                                        if python_exe.exists():
                                            version_key = f"{major}.{minor}"
                                            if version_key not in seen_versions:
                                                found_versions.append({
                                                    'command': [str(python_exe)],
                                                    'path': [str(python_exe)],
                                                    'version': version_key,
                                                    'full_version': version_str,
                                                    'display': f'python{major}.{minor}'
                                                })
                                                seen_versions.add(version_key)
                                                self.print_success(
                                                    f"{self.lang['found']}: "
                                                    f"Python {major}.{minor} at {exe_path}"
                                                )
                                    except Exception:
                                        continue
                                        
                                except OSError:
                                    break
                    except Exception:
                        continue
                
                # Fallback: Try py launcher if registry didn't find anything
                if not found_versions:
                    py_launcher = shutil.which('py')
                    if py_launcher:
                        for minor in [14, 13, 12, 11, 10]:
                            try:
                                result = subprocess.run(
                                    [py_launcher, f'-3.{minor}', '--version'],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    text=True,
                                    timeout=2
                                )
                                if result.returncode == 0 and 'Python' in result.stdout:
                                    ver_str = result.stdout.split()[1]
                                    ver_parts = ver_str.split('.')
                                    maj = int(ver_parts[0])
                                    min_detected = int(ver_parts[1])
                                    ver_key = f"{maj}.{min_detected}"
                                    if ver_key not in seen_versions:
                                        found_versions.append({
                                            'command': [py_launcher, f'-3.{min_detected}'],
                                            'path': [py_launcher, f'-3.{min_detected}'],
                                            'version': ver_key,
                                            'full_version': ver_str,
                                            'display': f'py -3.{min_detected}'
                                        })
                                        seen_versions.add(ver_key)
                            except Exception:
                                continue
                
                python_commands = []
            else:
                # Mac/Linux: standard Unix commands
                python_commands = [
                    'python3.14', 'python3.13', 'python3.12',
                    'python3.11', 'python3.10', 'python3', 'python'
                ]
            
            for cmd in python_commands:
                try:
                    # Try to get version directly first
                    version_result = subprocess.run(
                        [cmd, '--version'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=2
                    )
                    
                    if version_result.returncode != 0:
                        continue
                    
                    # Validate output format
                    version_output = version_result.stdout.strip()
                    if not version_output or 'Python' not in version_output:
                        continue
                    
                    # Parse version from output
                    try:
                        version_str = version_output
                        version_parts = version_str.split()[1].split('.')
                        major = int(version_parts[0])
                        minor = int(version_parts[1])
                    except (IndexError, ValueError):
                        continue
                    
                    # Support Python 3.10-3.14
                    if not (major == 3 and 10 <= minor <= 14):
                        continue
                    
                    # Skip if already found this version
                    version_key = f"{major}.{minor}"
                    if version_key in seen_versions:
                        continue
                    
                    # Use command name as path (as list for subprocess)
                    found_versions.append({
                        'command': [cmd],
                        'path': [cmd],
                        'version': version_key,
                        'full_version': version_str.split()[1],
                        'display': cmd
                    })
                    seen_versions.add(version_key)
                
                except Exception:
                    continue
            
            self.python_versions = found_versions
            
            if not found_versions:
                self.print_error(self.lang['no_python_found'])
                return False
            
            return True
    
    def select_python_version(self):
        """Auto-continue after detecting Python versions"""
        # This method is now just a placeholder
        # Python detection and selection happens in detect_python_versions()
        self.print_step(2, 6, 'selecting_python')
        
        if len(self.python_versions) == 1:
            self.selected_python = self.python_versions[0]
            display = (
                self.selected_python.get(
                    'display',
                    ' '.join(self.selected_python['command'])
                )
            )
            self.print_detail(
                f"{self.lang['selected']}: {display} "
                f"(Python {self.selected_python['version']})"
            )
            return True
        
        # Multiple versions: show menu in Vietnamese
        if self.interactive:
            print(f"\n{Colors.BOLD}Các phiên bản Python:{Colors.ENDC}")
            for i, py in enumerate(self.python_versions, 1):
                print(f"  {i}. {py['display']} - Python {py['full_version']}")
            
            while True:
                try:
                    choice = input(
                        f"\n{Colors.CYAN}Chọn phiên bản (Enter = 1): "
                        f"{Colors.ENDC}"
                    ).strip()
                    
                    if not choice:
                        choice = "1"
                    
                    idx = int(choice) - 1
                    if 0 <= idx < len(self.python_versions):
                        self.selected_python = self.python_versions[idx]
                        break
                    else:
                        self.print_error(self.lang['invalid_selection'])
                except ValueError:
                    self.print_error(self.lang['enter_number'])
        else:
            # Non-interactive: use first
            self.selected_python = self.python_versions[0]
        
        self.print_detail(
            f"{self.lang['selected']}: "
            f"{self.selected_python['display']} "
            f"(Python {self.selected_python['version']})"
        )
        return True
    
    def select_venv_configuration(self):
        """Select virtual environment configuration
        
        For Colab: Always use temp/session mode for packages (fast),
                   but config/API key stored in Drive (persistent)
        For others: Regular venv selection
        """
        self.print_step(3, 6, 'creating_venv')
        
        # Colab: Always use temp/session mode for packages
        # (API key will be read from Drive via VNSTOCK_CONFIG_PATH)
        if self.is_colab:
            self.venv_type = 'system'
            self.venv_path = None
            self.print_info(f"🔥 {self.lang['colab_temp_install']}")
            self.print_detail(f"   {self.lang['colab_temp_desc']}")
            self.print_detail(f"   ⚡ {self.lang['colab_temp_benefit']}")
            self.print_detail("   📁 API key sẽ được lưu trong Drive")
            return True
        
        # Codespaces: default to system Python (no venv)
        if self.is_codespaces:
            self.venv_type = 'system'
            self.venv_path = None
            self.print_info("GitHub Codespaces detected - using system Python")
            return True
        
        # Non-interactive: use custom venv path if provided, else default ~/.venv
        if not self.interactive:
            if getattr(self, 'venv_path_arg', None):
                self.venv_type = 'custom'
                self.venv_path = Path(self.venv_path_arg).expanduser()
                self.print_info(f"Dùng: {self.venv_path}")
            else:
                self.venv_type = 'default'
                self.venv_path = Path.home() / ".venv"
            return True
        
        # Interactive: show options
        print(f"\n{Colors.BOLD}{self.lang['creating_venv']}:{Colors.ENDC}")
        print("  1. Dùng ~/.venv (mặc định)")
        print("  2. Chỉ định đường dẫn tùy chỉnh")
        print("  3. Dùng Python hệ thống (không venv)")
        
        while True:
            choice = input(
                f"\n{Colors.CYAN}Lựa chọn (1-3, Enter = 1): "
                f"{Colors.ENDC}"
            ).strip()
            
            if not choice:
                choice = '1'
            
            if choice == '1':
                # Default: ~/.venv
                self.venv_type = 'default'
                self.venv_path = Path.home() / ".venv"
                self.print_info(f"Dùng: {self.venv_path}")
                return True
            
            elif choice == '2':
                # Custom path
                custom_path = input(
                    f"{Colors.CYAN}Nhập đường dẫn "
                    f"(~ để home): {Colors.ENDC}"
                ).strip()
                
                if custom_path:
                    self.venv_type = 'custom'
                    chosen_path = Path(custom_path).expanduser()
                    
                    # Detect if user entered a project path instead of venv path
                    if 'env' not in chosen_path.name.lower():
                        print(f"\n{Colors.YELLOW}⚠️ Cảnh báo: Đường dẫn '{chosen_path}' có vẻ là thư mục dự án chứ không phải thư mục môi trường ảo.{Colors.ENDC}")
                        suggest_venv = input(f"{Colors.CYAN}Bạn có muốn tạo môi trường ảo tại {chosen_path / '.venv'} không? (Y/n): {Colors.ENDC}").strip().lower()
                        if suggest_venv != 'n':
                            chosen_path = chosen_path / '.venv'
                            
                    self.venv_path = chosen_path
                    self.print_info(f"Dùng: {self.venv_path}")
                    return True
                else:
                    self.print_error(self.lang['invalid_selection'])
            
            elif choice == '3':
                # System Python (no venv)
                self.venv_type = 'system'
                self.venv_path = None
                self.print_info("Dùng Python hệ thống")
                return True
            
            else:
                self.print_error(self.lang['invalid_selection'])
    
    def check_python_version(self):
        """Check Python version"""
        version = sys.version_info
        py_ver = f"{version.major}.{version.minor}.{version.micro}"
        print(f"Current Python: {py_ver}")
        
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            self.print_error(f"Python 3.10+ required (found {py_ver})")
            return False
        
        self.print_success(f"Python {py_ver} is compatible")
        return True
    
    def create_virtual_environment(self):
        """Create/verify virtual environment based on config"""
        # If system Python selected, skip venv creation
        if self.venv_type == 'system':
            self.print_success("Dùng Python hệ thống")
            return True
        
        # Handle venv_path
        if self.venv_path is None:
            self.print_error("Venv path not configured")
            return False
        
        # Check if venv already exists and is healthy
        if self.venv_path.exists():
            if self._is_venv_healthy():
                self.print_detail(
                    f"Dùng venv hiện tại: {self.venv_path}"
                )
                return True
            else:
                # Venv corrupted, check if it's safe to delete
                is_safe_to_delete = (
                    (self.venv_path / "pyvenv.cfg").exists() or
                    any(env_name in self.venv_path.name.lower() for env_name in ['.venv', 'venv', 'env'])
                )
                
                if not is_safe_to_delete:
                    self.print_error(f"❌ NGHIÊM TRỌNG: Từ chối xóa thư mục {self.venv_path}")
                    self.print_error("Lý do: Thư mục này không giống môi trường ảo (không có pyvenv.cfg và tên không chứa 'env').")
                    self.print_error("Để bảo vệ an toàn cho source code của bạn, tiến trình cài đặt đã bị hủy.")
                    self.print_error("Vui lòng chỉ định đúng thư mục môi trường ảo (ví dụ: path/to/project/.venv).")
                    return False
                    
                # Venv corrupted and safe to delete, try to recreate
                self.print_warning(self.lang['venv_corrupted'])
                try:
                    shutil.rmtree(self.venv_path)
                except Exception as e:
                    self.print_error(
                        f"{self.lang['venv_removed_failed']}: {e}"
                    )
                    return False
        
        # Create new venv
        try:
            # Extract path if it's a list
            py_cmd = (
                self.selected_python['path'][0]
                if isinstance(self.selected_python['path'], list)
                else self.selected_python['path']
            )
            self.print_info(
                f"Tạo venv: {self.venv_path}"
            )
            
            # Create venv with uv
            if not ensure_uv_installed(py_cmd):
                self.print_error("Không thể cài đặt uv package manager")
                return False
            
            # Get UV command (handles different installation locations)
            uv_cmd = get_uv_command()
            
            subprocess.run(
                [uv_cmd, 'venv', str(self.venv_path), '--python', py_cmd],
                check=True,
                capture_output=not self.verbose
            )
            self.print_detail(f"Venv được tạo: {self.venv_path}")
            return True
        except Exception as e:
            self.print_error(f"Tạo venv thất bại: {e}")
            return False
    
    def _is_venv_healthy(self):
        """Check if venv directory is valid"""
        if not self.venv_path:
            return False
        
        if self.venv_type == 'system':
            return True
        
        if os.name == 'nt':
            return (self.venv_path / "Scripts" / "python.exe").exists()
        else:
            return (self.venv_path / "bin" / "python").exists()
    
    def get_pip_command(self):
        """Get pip command for venv"""
        if self.is_colab:
            # Colab: use system pip with --target flag
            # Extract path if it's a list
            py_path = (
                self.selected_python['path'][0]
                if isinstance(self.selected_python['path'], list)
                else self.selected_python['path']
            )
            return f"{py_path} -m pip"
        elif self.venv_path:
            if os.name == 'nt':
                return str(self.venv_path / "Scripts" / "pip")
            else:
                return str(self.venv_path / "bin" / "pip")
        # Fallback to selected Python's pip
        py_path = (
            self.selected_python['path'][0]
            if isinstance(self.selected_python['path'], list)
            else self.selected_python['path']
        )
        return f"{py_path} -m pip"
    
    def _satisfies_requirement(self, installed_ver: str, req_spec: str) -> bool:
        """Verify if installed version satisfies the requirement specifier"""
        if not req_spec:
            return True
            
        try:
            # Try using packaging (standard in Colab)
            from packaging.specifiers import SpecifierSet
            from packaging.version import parse as parse_version
            
            return parse_version(installed_ver) in SpecifierSet(req_spec)
        except (ImportError, Exception):
            # Fallback: Simple manual comparison for common cases (>=, ==)
            try:
                import re
                match = re.search(r'([>=<]+)\s*([0-9\.]+)', req_spec)
                if not match:
                    return True # Can't parse, assume OK to avoid breaking
                    
                op, target_ver = match.groups()
                
                def ver_to_tuple(v):
                    # Filter out non-numeric parts for simple comparison
                    parts = []
                    for x in re.findall(r'\d+', v):
                        try:
                            parts.append(int(x))
                        except ValueError:
                            pass
                    return tuple(parts)
                
                inst_tup = ver_to_tuple(installed_ver)
                target_tup = ver_to_tuple(target_ver)
                
                if op == '>=': return inst_tup >= target_tup
                if op == '==': return inst_tup == target_tup
                if op == '>': return inst_tup > target_tup
                if op == '<=': return inst_tup <= target_tup
                if op == '<': return inst_tup < target_tup
            except Exception:
                pass
                
        return True # Default to True (safe) if parsing fails

    def check_packages_installed(self, package_list=None):
        """Check if required packages are already installed (with version check)
        
        Args:
            package_list: List of requirement specs
            
        Returns:
            List of missing package specs (original req string)
        """
        import sys
        import io
        
        if package_list is None:
            package_list = REQUIRED_DEPENDENCIES
        
        # Parse package names from requirements
        # Store as tuples: (pkg_name, original_req)
        required_packages = []
        for req in package_list:
            if req and not req.startswith('#'):
                pkg_name = ""
                # Handle GitHub URLs
                if req.startswith('http') or req.startswith('git+'):
                    if '#egg=' in req:
                        pkg_name = req.split('#egg=')[1]
                    elif req.endswith('.git'):
                        pkg_name = req.split('/')[-1].replace('.git', '')
                    else:
                        pkg_name = req.split('/')[-1].split('-')[0]
                else:
                    pkg_name = (
                        req.split('>=')[0].split('==')[0].split('<')[0]
                           .split('>')[0].split('~')[0].strip()
                    )
                
                if pkg_name:
                    # Extract spec (everything after package name)
                    pkg_spec = req[len(pkg_name):].strip()
                    required_packages.append((pkg_name, pkg_spec, req))
        
        # Get installed packages dict {name: version}
        installed_dists = self._get_installed_distributions()
        
        missing_packages = []
        for pkg_name, pkg_spec, original_req in required_packages:
            # Normalize package name for comparison
            pkg_norm = pkg_name.lower().replace('_', '-')
            
            # Special handling for critical packages: Verify by import
            if pkg_norm in ['vnai', 'vnii']:
                try:
                    # Determine python executable
                    target_python = sys.executable
                    if not (self.is_colab or self.is_codespaces) and self.venv_path:
                        if os.name == 'nt':
                           target_python = str(self.venv_path / "Scripts" / "python.exe")
                        else:
                           target_python = str(self.venv_path / "bin" / "python")
                    
                    # Run import check
                    import_name = 'vnai' if 'vnai' in pkg_norm else 'vnii'
                    cmd = [target_python, '-c', f'import {import_name}']
                    result = subprocess.run(
                        cmd, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    )
                    if result.returncode != 0:
                        missing_packages.append(original_req)
                        continue
                except Exception:
                    missing_packages.append(original_req)
                    continue

            # Check if package is installed and verify version
            is_installed = False
            for installed_name, installed_version in installed_dists.items():
                inst_norm = installed_name.replace('_', '-')
                if inst_norm == pkg_norm:
                    # Match found, check version if on Colab
                    if self.is_colab:
                        if self._satisfies_requirement(installed_version, pkg_spec):
                            is_installed = True
                            self.log(f"Package satisfied: {pkg_norm} ({installed_version})", "INFO")
                        else:
                            self.log(f"Package version mismatch: {pkg_norm} {installed_version} vs {pkg_spec}", "INFO")
                            is_installed = False
                    else:
                        is_installed = True
                    break
            
            if not is_installed:
                missing_packages.append(original_req)
                
        return missing_packages
    
    def install_dependencies(self):
        """Install dependencies from predefined requirements.
        
        Uses REQUIRED_DEPENDENCIES or COLAB_REQUIREMENTS based on environment.
        Ensures vnstock core is always installed first (dependency order).
        
        For Colab: Take snapshot before/after install to identify new packages.
        """
        self.print_step(4, 6, 'installing_deps')
        
        # Colab: Snapshot packages BEFORE install (log to file only)
        packages_before = set()
        if self.is_colab:
            packages_before = self._get_installed_packages()
            self.log(f"Packages before install: {len(packages_before)}", "INFO")
            
        # Ensure uv is installed (critical for installation)
        self.print_info("Bootstrapping uv package manager (auto-install if missing)...")
        if not ensure_uv_installed():
            self.print_error("Failed to bootstrap uv. Please install 'uv' manually.")
            return False
        
        # Fetch requirements from URL (with fallback to hardcoded)
        # This ensures we always use the latest requirements from server
        if self.is_colab:
            self.print_info(self.lang['checking_packages'])
            requirements_list = self.fetch_requirements_from_url(is_colab=True)
            missing = self.check_packages_installed(requirements_list)
        else:
            self.print_info(self.lang['checking_packages'])
            requirements_list = self.fetch_requirements_from_url(is_colab=False)
            missing = self.check_packages_installed(requirements_list)
        
        # Early exit if nothing to install
        if not missing:
            self.print_success(self.lang['all_packages_installed'])
            return True
        
        # Show which packages need to be installed
        pkg_list = ', '.join(missing[:5])
        if len(missing) > 5:
            pkg_list += '...'
        
        if self.is_colab:
            self.print_info(
                f"Installing missing packages ({len(missing)}): {pkg_list}"
            )
        else:
            msg = (f"{self.lang['need_install_packages']} {len(missing)} "
                   f"{self.lang['packages']}: {pkg_list}")
            self.print_info(msg)
        
        # Filter to only missing packages for efficiency
        filtered_list = [
            req for req in requirements_list
            if any(missing_pkg in req for missing_pkg in missing)
            or req.startswith('https://')  # Always include GitHub URLs
        ]
        
        # Sort to ensure critical packages install first with --upgrade
        # typing_extensions: Required by pydantic_core (must override old versions)
        # vnai: Device fingerprinting (PyPI)
        # vnii: Licensing (Extra Index)
        critical_packages = [
            r for r in filtered_list 
            if any(pkg in r.lower() for pkg in ['vnai', 'vnii', 'typing-extensions', 'typing_extensions'])
        ]
        
        core_packages = [
            r for r in filtered_list 
            if 'vnstock' in r.lower()
            and r not in critical_packages
        ]
        
        other_packages = [
            r for r in filtered_list 
            if r not in critical_packages
            and r not in core_packages
        ]
        
        sorted_requirements = critical_packages + core_packages + other_packages
        
        # Create temp requirements file from sorted list
        tmp_req = Path("/tmp/vnstock_requirements.txt")
        tmp_req.write_text('\n'.join(sorted_requirements))
        
        pip_cmd = self.get_pip_command()
        
        progress = ProgressBar(total=100, prefix="Installing dependencies")
        
        try:

            # Show progress animation
            for p in range(0, 91, 10):
                progress.update(p)
                time.sleep(0.1)
            
            # Install dependencies using uv pip install with requirements URL
            # This ensures we get exactly the versions we want
            
            # Prepare uv command base
            uv_cmd = get_uv_command()
            uv_base = [uv_cmd, 'pip', 'install', '--python']
            
            # Get python executable path
            target_python = sys.executable
            if not (self.is_colab or self.is_codespaces):
                 if self.venv_path:
                     if os.name == 'nt':
                         target_python = str(self.venv_path / "Scripts" / "python.exe")
                     else:
                         target_python = str(self.venv_path / "bin" / "python")
            
            uv_base.append(target_python)
            
            common_args = [
                '--extra-index-url', VNSTOCKS_INDEX_URL,
                '-c', REQUIREMENTS_URL
            ]
            
            # Phase 1: Install critical packages with --upgrade to override old versions
            # This is essential for typing_extensions which may exist in user site-packages
            # with an old version that doesn't have Sentinel class
            if critical_packages:
                # self.print_detail("Installing critical packages (typing_extensions, vnai, vnii)...")
                subprocess.run(
                    uv_base + ['--upgrade'] + common_args + critical_packages,
                    capture_output=True,
                    timeout=120
                )

            # Phase 2: Install remaining
            remaining = core_packages + other_packages
            if remaining:
                uv_cmd = uv_base + common_args + remaining
                
                # Run command
                result = subprocess.run(
                    uv_cmd,
                    capture_output=True,
                    text=True,
                    timeout=600 if self.is_colab else 300
                )
            else:
                # Mock result if everything was in vnai_packages
                result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
            progress.update(100)
            progress.finish("Installed!")
            
            # Cleanup temp file if it was created (not used with uv direct list but good practice)
            tmp_req.unlink(missing_ok=True)
            
            if result.returncode != 0:
                self.print_warning("Some packages had warnings")
                if self.verbose:
                    print(result.stderr[:500])
            else:
                self.print_detail("Dependencies installed")
            
            self.log("Dependencies installed", "SUCCESS")
            
            # Colab: Log to file only (for debug)
            if self.is_colab:
                packages_after = self._get_installed_packages()
                deps_installed = packages_after - packages_before
                self.log(
                    f"Dependencies installed: {len(deps_installed)} packages",
                    "INFO"
                )
            
            return True
            
        except subprocess.TimeoutExpired:
            progress.finish("Timeout!")
            tmp_req.unlink(missing_ok=True)
            self.print_error("Installation timeout")
            return False
        except Exception as e:
            progress.finish("Failed!")
            tmp_req.unlink(missing_ok=True)
            self.print_error(f"Failed to install dependencies: {e}")
            return False
    
    def _get_installed_distributions(self) -> dict:
        """Get dict of installed packages {name_lower: version}"""
        try:
            # Determine Python executable
            if not (self.is_colab or self.is_codespaces) and self.venv_path:
                if os.name == 'nt':
                    py_path = str(self.venv_path / "Scripts" / "python.exe")
                else:
                    py_path = str(self.venv_path / "bin" / "python")
            else:
                py_path = (
                    self.selected_python['path'][0]
                    if isinstance(self.selected_python['path'], list)
                    else self.selected_python['path']
                )
            
            # Get list of installed packages as JSON
            result = subprocess.run(
                [py_path, '-m', 'pip', 'list', '--format=json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return {}
            
            packages = json.loads(result.stdout)
            # Return dict of {name_lower: version}
            # Normalize names to use hyphens for consistency with check logic if needed
            # But simple lower() is robust enough if check logic handles it
            return {pkg['name'].lower(): pkg['version'] for pkg in packages}
            
        except Exception as e:
            self.print_warning(f"Could not get package list: {e}")
            return {}

    def _get_installed_packages(self) -> set:
        """Get set of installed package names"""
        return set(self._get_installed_distributions().keys())
    
    def copy_vnstock_packages_to_drive(self):
        """Copy newly installed packages (including dependencies) to Drive
        
        After fast temp installation, copy ALL newly installed packages to Drive
        so they survive runtime restarts. Uses diff from install_dependencies().
        
        Returns:
            bool: True if successful or not needed
        """
        if not self.is_colab:
            return True  # Only for Colab
        
        # Check if we have the list of newly installed packages
        if not hasattr(self, 'newly_installed_packages'):
            self.print_warning("No package diff available, skipping backup")
            return True
        
        if not self.newly_installed_packages:
            self.print_info("No new packages to backup")
            return True
        
        drive_venv = Path("/content/drive/MyDrive/.venv")
        
        # Find site-packages location
        py_path = (
            self.selected_python['path'][0]
            if isinstance(self.selected_python['path'], list)
            else self.selected_python['path']
        )
        
        # Get site-packages path from Python
        result = subprocess.run(
            [py_path, '-c', 
             'import site; print(site.getsitepackages()[0])'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            self.print_warning("Could not find site-packages location")
            return True  # Non-critical, continue
        
        site_packages = Path(result.stdout.strip())
        if not site_packages.exists():
            self.print_warning(f"Site-packages not found: {site_packages}")
            return True
        
        # Create Drive venv directory
        drive_venv.mkdir(parents=True, exist_ok=True)
        
        self.print_info(
            f"📦 Backing up {len(self.newly_installed_packages)} packages..."
        )
        copied_count = 0
        skipped_count = 0
        
        for pkg_name in sorted(self.newly_installed_packages):
            # Find package folders (handle variations)
            # Package can be: pkg_name, pkg_name-x.y.z.dist-info, pkg_name.py, etc.
            pkg_name_underscore = pkg_name.replace('-', '_')
            pkg_patterns = [
                pkg_name,
                f"{pkg_name}-*",
                pkg_name_underscore,
                f"{pkg_name_underscore}-*"
            ]
            
            pkg_folders = []
            for pattern in pkg_patterns:
                pkg_folders.extend(site_packages.glob(pattern))
            
            if not pkg_folders:
                skipped_count += 1
                continue  # Package not found (might be built-in), skip
            
            for src_folder in pkg_folders:
                # Skip if not a directory or is a .pyc cache
                if not src_folder.is_dir() or '__pycache__' in src_folder.name:
                    continue
                
                dst_folder = drive_venv / src_folder.name
                
                try:
                    # Remove existing if present
                    if dst_folder.exists():
                        shutil.rmtree(dst_folder)
                    
                    # Copy package folder
                    shutil.copytree(src_folder, dst_folder, 
                                   ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    copied_count += 1
                    
                    # Log to file only (for debug)
                    if copied_count % 10 == 0:
                        self.log(f"Copied {copied_count} folders", "INFO")
                    
                except Exception as e:
                    self.log(f"Failed to copy {src_folder.name}: {e}", "WARNING")
        
        if copied_count > 0:
            self.print_success(
                f"Backed up {copied_count} folders to Drive: {drive_venv}"
            )
            # Log details to file
            self.log(
                f"Backup complete: {copied_count} copied, "
                f"{skipped_count} skipped",
                "INFO"
            )
            return True
        else:
            self.print_warning("No packages copied")
            return True  # Non-critical
    
    def install_critical_dependencies(self):
        """Install critical system dependencies needed by installer"""
        # Check which packages are missing
        missing = []
        for pkg_name, import_name in CRITICAL_DEPENDENCIES.items():
            try:
                __import__(import_name)
            except ImportError:
                missing.append(pkg_name)
        
        if not missing:
            # All packages already installed
            return True
        
        # Print info about missing packages
        missing_str = ', '.join(missing)
        if self.is_vietnamese:
            msg = f"Đang kiểm tra các gói hệ thống ({missing_str})..."
        else:
            msg = f"Checking system packages ({missing_str})..."
        
        self.print_info(msg)
        
        # Try to install missing packages
        try:
            # Extract path if it's a list
            py_cmd = (
                self.selected_python['path'][0]
                if isinstance(self.selected_python['path'], list)
                else self.selected_python['path']
            )
            
            # Fetch requirements to get precise versions
            # This allows critical packages to follow web-defined versions
            all_reqs = self.fetch_requirements_from_url(self.is_colab)
            
            # Helper to find versioned string
            def get_versioned_pkg(pkg_name):
                # Special case for typing_extensions (hyphen/underscore)
                normalized_pkg = pkg_name.lower().replace('_', '-')
                for r in all_reqs:
                    if normalized_pkg in r.lower().replace('_', '-'):
                        return r
                return pkg_name  # Fallback to name only (latest)

            # Install each missing package ensuring version match
            for pkg in missing:
                versioned_pkg = get_versioned_pkg(pkg)
                
                if self.is_vietnamese:
                    self.print_info(f"Đang cài đặt {versioned_pkg}...")
                else:
                    self.print_info(f"Installing {versioned_pkg}...")
                
                # Use uv pip install for critical dependencies too
                # Target the python executable appropriately
                uv_cmd = get_uv_command()
                # Use --upgrade to ensure we get the required version, overriding system packages
                # This is crucial for typing_extensions in Codespaces
                uv_args = [uv_cmd, 'pip', 'install', '--upgrade', '--python']
                if self.is_colab or self.is_codespaces:
                    uv_args.append(sys.executable)
                elif self.venv_path:
                    # Important: if using venv, check if python is integer
                    # (self.selected_python['path'] might be weird, better rely on venv_path)
                     if os.name == 'nt':
                         uv_args.append(str(self.venv_path / "Scripts" / "python.exe"))
                     else:
                         uv_args.append(str(self.venv_path / "bin" / "python"))
                else:
                     uv_args.append(sys.executable)

                uv_args.extend([
                    '--extra-index-url', VNSTOCKS_INDEX_URL,
                    '-c', REQUIREMENTS_URL,
                    versioned_pkg
                ])
                
                result = subprocess.run(
                    uv_args,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode != 0:
                    if self.is_vietnamese:
                        self.print_warning(
                            f"Cảnh báo: Không cài được {pkg} "
                            f"(sẽ thử tiếp tục)"
                        )
                    else:
                        self.print_warning(
                            f"Warning: Failed to install {pkg} "
                            f"(will try to continue)"
                        )
                else:
                    self.print_success(f"{pkg} installed")
            
            return True
            
        except Exception as e:
            if self.is_vietnamese:
                self.print_warning(f"Lỗi khi cài dependencies: {e}")
            else:
                self.print_warning(f"Error installing dependencies: {e}")
            return True  # Don't fail, try to continue anyway
    
    def get_api_key(self, provided_api_key=None):
        """Get API key from user and save to config
        
        Args:
            provided_api_key: API key passed via command line (--api-key)
        """
        self.print_step(5, 6, 'api_auth')

        # CRITICAL: Ensure vnai and vnii are installed before using them
        # These are required for device identification
        self.print_info(
            "Ensuring critical packages (vnai, vnii) are available..."
        )
        if not self.install_critical_dependencies():
            self.print_warning(
                "Failed to install critical packages, "
                "attempting to continue..."
            )

        # Priority: provided_api_key > env var > saved config > prompt user
        api_key = provided_api_key or os.environ.get('VNSTOCK_API_KEY', '')
        
        # Check saved config if not provided yet
        if not api_key:
            saved_key = load_api_key()
            if saved_key:
                # Validate the saved key
                username, _ = get_username_from_api(saved_key)
                if username != 'Unknown':
                    api_key = saved_key
                    if self.is_vietnamese:
                        self.print_success(f"Phát hiện phiên đăng nhập hợp lệ: {username}")
                    else:
                        self.print_success(f"Found valid session: {username}")
        
        if api_key:
            # Save API key to ~/.vnstock/api_key.json (ensure it's persisted/refreshed)
            save_api_key(api_key)
            if not provided_api_key and not os.environ.get('VNSTOCK_API_KEY'):
                # Already logged success for session above
                pass
            else:
                self.print_success(self.lang['using_env_key'])
            return api_key
        
        if not self.interactive:
            self.print_warning(self.lang['no_api_key'])
            return None
        
        # Interactive: prompt user to get API key from their account
        print(f"\n{Colors.BOLD}{self.lang['api_auth']}:{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_DOT)
        print()
        
        if self.is_vietnamese:
            print(f"{Colors.CYAN}Lấy API key từ tài khoản "
                  f"của bạn:{Colors.ENDC}")
            print("  1. Truy cập: https://vnstocks.com/account")
            print("  2. Sao chép API key từ phần 'API Key của bạn'")
            print("  3. Dán vào đây")
        else:
            print(f"{Colors.CYAN}Get API key from your account:"
                  f"{Colors.ENDC}")
            print("  1. Visit: https://vnstocks.com/account")
            print("  2. Copy your API key from 'Your API Key' section")
            print("  3. Paste it here")
        
        # Prompt for API key
        if self.is_vietnamese:
            prompt = f"\n{Colors.CYAN}{self.lang['enter_api_key']}: "
            prompt += f"{Colors.ENDC}"
        else:
            prompt = f"\n{Colors.CYAN}{self.lang['enter_api_key']}: "
            prompt += f"{Colors.ENDC}"
        
        api_key = input(prompt).strip()
        
        if api_key:
            # Save API key to ~/.vnstock/api_key.json
            save_api_key(api_key)
            self.print_success(self.lang['api_key_entered'])
            
            
            # Create user info file with system information
            venv_path_arg = str(self.venv_path) if self.venv_path else None
            log_path = os.path.expanduser('~/vnstock_installer_debug.log')
            with open(log_path, 'a') as f:
                f.write(f"DEBUG authenticate_api: self.venv_path={self.venv_path}, venv_path_arg={venv_path_arg}\n")
                f.flush()
            
            device_info = generate_device_id(venv_path=venv_path_arg)
            user_info = create_user_info(
                python_executable=(
                    self.selected_python['path'][0]
                    if isinstance(self.selected_python['path'], list)
                    else self.selected_python['path']
                ),
                venv_path=str(self.venv_path) if self.venv_path else None,
                device_info=device_info,
                api_key=api_key
            )
            save_user_info(user_info)
            
            if self.is_vietnamese:
                self.print_info("✓ Đã lưu thông tin cấu hình")
            else:
                self.print_info("✓ Configuration saved")
            
            return api_key
        else:
            self.print_error(self.lang['no_api_key'])
            return None
    
    def validate_installation(self):
        """Validate that critical core packages are installed"""
        msg_key = 'validating'
        msg = (
            self.lang.get(msg_key, "Validating installation")
        )
        self.print_step(7, 7, message=msg)
        
        # Core packages to verify (required for vnstock to function)
        core_packages = {
            'numpy': 'numpy',
            'pandas': 'pandas',
            'requests': 'requests',
            'vnstock': 'vnstock',
        }
        
        missing_core = []
        
        # Validate core packages only
        # (vnstock modules may fail to import due to missing
        # sub-dependencies like pyarrow, but folders are there)
        checking_msg = (
            self.lang.get('checking_core', 'Checking core...')
        )
        self.print_info(checking_msg)
        for pkg_name, import_name in core_packages.items():
            if not self._check_package_import(import_name):
                missing_core.append(pkg_name)
                self.print_error(f"✗ {pkg_name}")
            else:
                self.print_success(f"✓ {pkg_name}")
        
        # Summary and recommendations
        if missing_core:
            return self._show_core_error(missing_core)
        else:
            success_msg = (
                self.lang.get('validation_complete',
                              '✓ Installation successful!')
            )
            self.print_success(success_msg)
            return True
    
    def _check_package_import(self, import_name: str) -> bool:
        """Check if a package can be imported"""
        try:
            # Get python executable
            if self.is_colab or self.is_codespaces:
                py_cmd = (
                    self.selected_python['path'][0]
                    if isinstance(self.selected_python['path'], list)
                    else self.selected_python['path']
                )
            elif self.venv_path and self.venv_type != 'system':
                if os.name == 'nt':
                    py_cmd = str(self.venv_path / "Scripts" / "python.exe")
                else:
                    py_cmd = str(self.venv_path / "bin" / "python")
            else:
                py_cmd = (
                    self.selected_python['path'][0]
                    if isinstance(self.selected_python['path'], list)
                    else self.selected_python['path']
                )
            
            result = subprocess.run(
                [py_cmd, '-c', f'import {import_name}; print("OK")'],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0 and 'OK' in result.stdout
        except Exception:
            return False
    
    def _show_core_error(self, missing_core):
        """Show error for missing core packages"""
        print()
        print(ASCIIArt.DIVIDER_THICK)
        error_title = (
            self.lang.get('install_incomplete',
                          '❌ INSTALLATION INCOMPLETE')
        )
        print(Colors.FAIL + error_title + Colors.ENDC)
        print(ASCIIArt.DIVIDER_THICK)
        
        missing_label = (
            self.lang.get('missing_core', 'Missing core packages:')
        )
        print(f"\n{Colors.FAIL}{missing_label}{Colors.ENDC}")
        for pkg in missing_core:
            print(f"  • {pkg}")
        
        causes_label = (
            self.lang.get('possible_causes', 'Possible causes:')
        )
        print(f"\n{Colors.OKBLUE}{causes_label}{Colors.ENDC}")
        print("  1. " + self.lang.get('install_interrupted',
                                      'Installation interrupted'))
        print("  2. " + self.lang.get('disk_network_issue',
                                      'Disk or network issues'))
        print("  3. " + self.lang.get('python_incompatible',
                                      'Incompatible Python'))
        print("  4. " + self.lang.get('venv_issue',
                                      'Virtual environment issues'))
        
        solutions_label = (
            self.lang.get('solutions', 'Solutions:')
        )
        print(f"\n{Colors.CYAN}{solutions_label}{Colors.ENDC}")
        print("  1. " + self.lang.get('try_reinstall',
                                      'Try reinstalling:'))
        packages_str = ' '.join(missing_core)
        print(f"     pip install --upgrade {packages_str}")
        print()
        print("  2. " + self.lang.get('consult_guide',
                                      'Consult troubleshooting:'))
        link = (
            "https://vnstocks.com/onboard-member/"
            "cai-dat-go-loi/giai-quyet-loi-thuong-gap"
        )
        print(f"     {Colors.UNDERLINE}{link}{Colors.ENDC}")
        print()
        
        return False
    
    def run_vnstock_installer(self, api_key=None):
        """Run the main vnstock-installer.py script"""
        self.print_step(6, 6, 'running_installer')
        
        # Find installer script in same directory
        script_dir = Path(__file__).parent
        installer_path = script_dir / "vnstock-installer.py"
        
        if not installer_path.exists():
            self.print_error(f"Installer not found: {installer_path}")
            return False
        
        # Log to file only (don't print to console)
        self.log("Running vnstock-installer.py", "INFO")
        
        # Get Python executable
        # Colab/Codespaces: use system Python (no real venv)
        # Local: use venv Python if exists
        if self.is_colab or self.is_codespaces:
            py_cmd = (
                self.selected_python['path'][0]
                if isinstance(self.selected_python['path'], list)
                else self.selected_python['path']
            )
        elif self.venv_path and self.venv_type != 'system':
            if os.name == 'nt':
                py_cmd = str(self.venv_path / "Scripts" / "python.exe")
            else:
                py_cmd = str(self.venv_path / "bin" / "python")
        else:
            py_cmd = (
                self.selected_python['path'][0]
                if isinstance(self.selected_python['path'], list)
                else self.selected_python['path']
            )
        
        # Prepare environment variables
        env = os.environ.copy()
        
        # Pass venv info to installer
        env['VNSTOCK_LANGUAGE'] = self.language
        
        # Colab: Use system Python but point config to Drive
        if self.is_colab:
            env['VNSTOCK_VENV_TYPE'] = 'system'
            # Point to Drive for API key persistence
            config_path = '/content/drive/MyDrive/.vnstock'
            env['VNSTOCK_CONFIG_PATH'] = config_path
            # Ensure config directory exists
            Path(config_path).mkdir(parents=True, exist_ok=True)
        else:
            # Non-Colab: regular venv handling
            env['VNSTOCK_VENV_TYPE'] = self.venv_type or 'default'
            if self.venv_path:
                env['VNSTOCK_VENV_PATH'] = str(self.venv_path)
        
        if api_key:
            env['VNSTOCK_API_KEY'] = api_key
        
        # Device registration handled by vnstock-installer.py
        # (VNSTOCK_SKIP_REGISTER removed - was causing skip)
        
        try:
            # Run installer (no stdin needed, uses env vars)
            process = subprocess.Popen(
                [py_cmd, str(installer_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1
            )
            
            stdout, _ = process.communicate(timeout=600)
            
            # Parse output to check for failures
            failed_count = 0
            success_count = 0
            device_limit_exceeded = False
            
            # Check for device limit error FIRST (to avoid printing logs)
            for line in stdout.split('\n'):
                if 'device limit exceeded' in line.lower():
                    device_limit_exceeded = True
                    break
            
            # Handle device limit exceeded error (skip all other output)
            if device_limit_exceeded:
                if self.is_vietnamese:
                    print(f"\n{Colors.FAIL}❌ Vượt quá giới hạn thiết bị!"
                          f"{Colors.ENDC}")
                    print(f"{Colors.WARNING}Gói Golden của bạn chỉ cho phép "
                          f"2 thiết bị mỗi hệ điều hành.{Colors.ENDC}")
                    print(f"{Colors.CYAN}Hướng dẫn giải quyết:{Colors.ENDC}")
                    print("  1. Vào trang: "
                          "https://vnstocks.com/account?section=devices")
                    print("  2. Xóa các thiết bị không còn sử dụng")
                    print("  3. Chạy lại installer")
                    print(f"\n{Colors.YELLOW}Sau khi xóa thiết bị, "
                          f"chạy lại lệnh cài đặt.{Colors.ENDC}")
                else:
                    print(f"\n{Colors.FAIL}❌ Device limit exceeded!"
                          f"{Colors.ENDC}")
                    print(f"{Colors.WARNING}Your Golden plan allows only "
                          f"2 devices per OS.{Colors.ENDC}")
                    print(f"{Colors.CYAN}How to fix:{Colors.ENDC}")
                    print("  1. Go to: "
                          "https://vnstocks.com/account?section=devices")
                    print("  2. Remove unused devices")
                    print("  3. Run installer again")
                    print(f"\n{Colors.YELLOW}After removing devices, "
                          f"run the installer again.{Colors.ENDC}")
                self.log("Device limit exceeded - user needs to remove "
                         "devices", "ERROR")
                return False
            
            # Show output and detect failures (only if not device limit)
            for line in stdout.split('\n'):
                if line.strip():
                    # Color code based on content
                    if 'error' in line.lower() or 'failed' in line.lower():
                        print(f"{Colors.FAIL}{line}{Colors.ENDC}")
                        # Count failed packages
                        if '❌ Failed:' in line or 'failed:' in line.lower():
                            try:
                                # Extract number from "❌ Failed: 4"
                                if '❌ Failed:' in line:
                                    parts = line.split('❌ Failed:')[1]
                                    num = int(parts.strip().split()[0])
                                    failed_count = num
                            except Exception:
                                pass
                    elif ('success' in line.lower() or
                          'complete' in line.lower()):
                        print(f"{Colors.OKGREEN}{line}{Colors.ENDC}")
                        # Count successful packages
                        if '✅ Successful:' in line:
                            try:
                                parts = line.split('✅ Successful:')[1]
                                success_count = int(parts.strip().split()[0])
                            except Exception:
                                pass
                    else:
                        print(line)
            
            # Check if installation was actually successful
            if failed_count > 0:
                msg = f"VNStock installation failed: {failed_count} packages"
                self.print_error(msg)
                log_msg = f"Check logs: {self.log_file}"
                self.print_warning(log_msg)
                self.log(
                    f"VNStock installer failed: {failed_count} packages",
                    "ERROR"
                )
                return False
            elif process.returncode == 0 or success_count > 0:
                self.print_success("VNStock installed successfully!")
                self.log("VNStock installer completed", "SUCCESS")
                return True
            else:
                self.print_error(
                    f"Installer failed with code {process.returncode}"
                )
                self.log(
                    f"Installer failed: code {process.returncode}",
                    "ERROR"
                )
                return False
                
        except subprocess.TimeoutExpired:
            process.kill()
            self.print_error("Installer timeout (10 minutes)")
            return False
        except Exception as e:
            self.print_error(f"Failed to run installer: {e}")
            return False
    
    def show_usage_instructions(self):
        """Show usage instructions"""
        self.print_step(7, 7, "Installation Complete!")
        
        print(f"\n{Colors.OKGREEN}{ASCIIArt.SUCCESS}{Colors.ENDC}")
        
        # Language-specific messages
        if self.language == 'vi':
            quick_start = "📚 Hướng Dẫn Nhanh:"
            colab_step1_label = "1. Kết nối Drive, thêm ô lệnh sau và chạy đầu tiên:"
            colab_step2_label = "2. Bắt đầu sử dụng VNStock:"
            important_notes = "💡 Lưu Ý Quan Trọng:"
            note1 = "   • Các thư viện đã được lưu trữ vào Google Drive"
            note2 = "   • Thông tin người dùng được lưu trữ để sử dụng nhanh vào phiên tiếp theo"
            note3 = "   • Phiên làm việc sau: Chỉ cần thêm sys.path để dùng lại thư viện đã cài mà không cần chạy lại installer"
            activate_venv = "1. Kích hoạt môi trường ảo:"
            start_vnstock = "2. Bắt đầu sử dụng VNStock:"
            docs_label = "📖 Tài Liệu & Xử Lý Sự Cố:"
            log_label = "File log:"
        else:
            quick_start = "📚 Quick Start Guide:"
            colab_step1_label = "1. Add to first cell:"
            colab_step2_label = "2. Start using VNStock:"
            important_notes = "💡 Important Notes:"
            note1 = "   • Packages backed up to Drive"
            note2 = "   • API key stored in Drive (persistent)"
            note3 = "   • After restart: Just add sys.path (no reinstall!)"
            activate_venv = "1. Activate virtual environment:"
            start_vnstock = "2. Start using VNStock:"
            docs_label = "📖 Documentation & Troubleshooting:"
            log_label = "Log file:"
        
        print(f"\n{Colors.BOLD}{quick_start}{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_DOT)
        
        if self.is_colab:
            # Google Colab specific instructions (with sys.path to Drive venv)
            # Step 1: Restore config from Drive
            print(f"\n{Colors.BOLD}⚠️  Sử dụng môi trường đã cài ở phiên làm việc tiếp theo:{Colors.ENDC}")
            
            # Step 2: Add to first cell
            msg = (
                f"\n{Colors.CYAN}{colab_step1_label}{Colors.ENDC}"
            )
            print(msg)
            print("import sys")
            print('sys.path.insert(0, "/content/drive/MyDrive/.venv")')
            print("!cp -r /content/drive/MyDrive/.vnstock /root/.vnstock")
            
            msg2 = f"\n{Colors.CYAN}{colab_step2_label}{Colors.ENDC}"
            print(msg2)
            print("from vnstock_data import Listing")
            print("Listing().all_symbols()")
            
            print(f"\n{Colors.BOLD}{important_notes}{Colors.ENDC}")
            print(note1)
            print(note2)
            print(note3)
        else:
            # Regular environment instructions
            if self.venv_path:
                msg = f"\n{Colors.CYAN}{activate_venv}{Colors.ENDC}"
                print(msg)
                if os.name == 'nt':
                    print(f"{self.venv_path}\\Scripts\\activate")
                else:
                    print(f"source {self.venv_path}/bin/activate")
            
            msg = f"\n{Colors.CYAN}{start_vnstock}{Colors.ENDC}"
            print(msg)
            print("python")
            print(">>> from vnstock_data import Listing")
            print(">>> Listing().all_symbols()")
        
        print(f"\n{Colors.CYAN}{docs_label}{Colors.ENDC}")
        print("• Tài liệu chính: https://vnstocks.com/onboard-member")
        setup_url = (
            "https://vnstocks.com/onboard-member/"
            "cai-dat-go-loi/cai-dat-nang-cao"
        )
        print(f"• Cài đặt nâng cao: {setup_url}")
        
        print(f"\n{Colors.GREY}{log_label} {self.log_file}{Colors.ENDC}")
        print(ASCIIArt.DIVIDER_THICK)
        print()
    
    def run(self, api_key_arg=None):
        """Main installation flow
        
        Args:
            api_key_arg: API key passed via command line
        """
        # Colab: Handle Google Drive (Optional)
        if self.is_colab:
            self.print_info(f"🔍 {self.lang['detected_colab']}")
            self.mount_google_drive()
            
            # Step 0: Restore config from Drive early (if available)
            # This ensures generate_device_id can find persistent ID
            if self.is_drive_mounted:
                drive_vnstock = Path("/content/drive/MyDrive/.vnstock")
                home_vnstock = Path.home() / ".vnstock"
                if drive_vnstock.exists():
                    try:
                        home_vnstock.mkdir(parents=True, exist_ok=True)
                        for item in drive_vnstock.iterdir():
                            if item.is_file():
                                shutil.copy2(item, home_vnstock / item.name)
                        self.print_info("✓ Đã khôi phục cấu hình từ Google Drive")
                    except Exception as e:
                        self.log(f"Config restoration failed: {e}", "WARNING")

        # Step 1: Detect and select Python version (combined)
        if not self.detect_python_versions():
            return False
        
        if not self.select_python_version():
            return False
        
        # Step 2: Select venv configuration (Colab temp or local)
        if not self.select_venv_configuration():
            return False
        
        # Step 3: Create venv (skip on Colab - use system Python)
        if not self.is_colab:
            if not self.create_virtual_environment():
                return False
        
        # Colab: Snapshot packages BEFORE any installation
        if self.is_colab:
            self.packages_before_sponsor = self._get_installed_packages()
            # Log to file only
            self.log(
                f"Snapshot: {len(self.packages_before_sponsor)} packages",
                "INFO"
            )
        
        # Step 4: Install dependencies (from centralized URL)
        if not self.install_dependencies():
            return False
        
        # Step 5: Install critical system dependencies
        if not self.install_critical_dependencies():
            return False
        
        # Step 5.5: Get API key (with command line override)
        api_key = self.get_api_key(provided_api_key=api_key_arg)
        
        # Step 6: Run vnstock-installer.py (installs sponsor packages)
        if not self.run_vnstock_installer(api_key=api_key):
            return False
        
            if self.is_drive_mounted:
                self.print_info("✓ Đã hoàn tất cài đặt (Chế độ Colab)")
        
        # Step 6.6: Copy config (.vnstock) from home to Drive (Colab only)
        # Backup for persistence across runtime restarts
        if self.is_colab and self.is_drive_mounted:
            home_vnstock = Path.home() / ".vnstock"
            drive_vnstock = Path("/content/drive/MyDrive/.vnstock")
            if home_vnstock.exists():
                try:
                    # Copy all config files from home to Drive
                    drive_vnstock.mkdir(parents=True, exist_ok=True)
                    for item in home_vnstock.iterdir():
                        if item.is_file():
                            shutil.copy2(item, drive_vnstock / item.name)
                    self.log(
                        f"Config backed up to Drive: {drive_vnstock}",
                        "INFO"
                    )
                except Exception as e:
                    self.log(f"Could not backup config to Drive: {e}", "WARNING")
        
        # Step 7: Validate installation
        if not self.validate_installation():
            return False
        
        # Final: Show instructions
        self.show_usage_instructions()
        
        return True


def main():
    """Main entry point"""
    # Detect if running in non-interactive environment
    is_interactive_terminal = sys.stdin.isatty()
    
    parser = argparse.ArgumentParser(
        description="VNStock CLI Installer - Text-based Installation Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python vnstock_cli.py
  
  # Non-interactive mode (for automation)
  python vnstock_cli.py --non-interactive
  
  # Verbose output
  python vnstock_cli.py --verbose
  
Perfect for:
  - Google Colab notebooks
  - Linux VPS servers
  - Docker containers
  - SSH sessions
  - Headless environments
        """
    )
    
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without prompts (for automation)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    
    parser.add_argument(
        "--language", "--lang",
        choices=['vi', 'en'],
        default='vi',
        help="Interface language: vi (Vietnamese) or en (English). Default: vi"
    )
    
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="VNStock API key for sponsor package installation"
    )
    
    parser.add_argument(
        "--venv-path",
        type=str,
        default=os.environ.get('VNSTOCK_VENV_PATH', None),
        help="Path for virtual environment. Defaults to ~/.venv or VNSTOCK_VENV_PATH env var."
    )
    
    args = parser.parse_args()
    
    # Force non-interactive if stdin is not a terminal (Docker, SSH pipe)
    if not is_interactive_terminal:
        args.non_interactive = True
    
    # Show logo and subtitle at startup (one time)
    print("\n" + Colors.VNSTOCK_GREEN + ASCIIArt.LOGO + Colors.ENDC)
    subtitle = (
        "Công cụ tải dữ liệu chứng khoán #1 Việt Nam từ API công khai trong Python"
    )
    print(Colors.VNSTOCK_GREEN + subtitle + Colors.ENDC)
    print(f"{Colors.GREY}CLI Installer v{__version__}{Colors.ENDC}")
    print(Colors.VNSTOCK_GREEN + ASCIIArt.DIVIDER_THICK + Colors.ENDC)
    
    # STEP 0: Select Language FIRST (interactive mode)
    language = args.language
    if not args.non_interactive and is_interactive_terminal:
        # Only prompt for language in interactive mode with TTY
        print(f"\n{Colors.BOLD}Chọn ngôn ngữ / Select Language:{Colors.ENDC}")
        print("  1. Tiếng Việt (Vietnamese)")
        print("  2. English")
        try:
            choice = input(
                f"\n{Colors.CYAN}Lựa chọn (Enter = 1): {Colors.ENDC}"
            ).strip()
            if choice == '2':
                language = 'en'
        except EOFError:
            # Fallback if input fails
            pass
    
    # Pass language to environment for vnstock-installer.py
    os.environ['VNSTOCK_LANGUAGE'] = language
    
    installer = VNStockCLIInstaller(
        interactive=not args.non_interactive,
        verbose=args.verbose,
        language=language,
        venv_path_arg=args.venv_path
    )
    
    try:
        success = installer.run(api_key_arg=args.api_key)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Installation cancelled by user.{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{Colors.FAIL}Unexpected error: {e}{Colors.ENDC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
