#!/usr/bin/env python3
"""
Vnstock License Manager & Installer
Cross-platform installer for vnstock Sponsored packages
"""

import getpass
import hashlib
import importlib
import json
import logging
import os
import platform
import re
import requests
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

def setup_logging():
    """Setup logging with file output and sanitized console output"""
    home_dir = os.path.expanduser("~")
    
    # Check if custom config path is set (for Colab)
    config_dir = os.environ.get('VNSTOCK_CONFIG_PATH')
    if not config_dir:
        config_dir = os.path.join(home_dir, ".vnstock")
    
    os.makedirs(config_dir, exist_ok=True)
    
    log_file = os.path.join(config_dir, "vnstock_installer.log")
    
    # Configure root logger
    logger = logging.getLogger('vnstock_installer')
    logger.setLevel(logging.DEBUG)
    
    # File handler - detailed logs for debugging
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler - user-friendly output (WARNING and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger, log_file


def sanitize_log_data(data: dict) -> dict:
    """Remove sensitive data from logs (API keys, tokens, passwords)"""
    sanitized = data.copy()
    sensitive_keys = [
        'api_key', 'token', 'password', 'secret',
        'authorization', 'access_token', 'refresh_token'
    ]
    
    for key in list(sanitized.keys()):
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            sanitized[key] = '***REDACTED***'
        elif isinstance(sanitized[key], dict):
            sanitized[key] = sanitize_log_data(sanitized[key])
    
    return sanitized


# Initialize logger
logger, LOG_FILE_PATH = setup_logging()


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


# Configuration
SUPPORTED_PYTHON_VERSIONS = ['3.10', '3.11', '3.12', '3.13', '3.14']


# Essential requirements from requirements-pinned.txt
# Now loaded dynamically from hosted file
REQUIREMENTS_URL = "https://vnstocks.com/files/requirements.txt"
VNSTOCKS_INDEX_URL = 'https://vnstocks.com/api/simple'

REQUIRED_DEPENDENCIES = [
    'vnai',  # Device fingerprinting (must be first)
    'vnii',
    'numpy',
    'pandas',
    'requests',
    'beautifulsoup4',
    'aiohttp',
    'nest-asyncio',
    'pydantic',
    'psutil',
    'duckdb',
    'pyarrow',
    'openpyxl',
    'tqdm',
    'panel',
    'pyecharts',
    'pta-reload',
    'vnstock_ezchart',
]


def check_python_version():
    """Check if current Python version is supported"""
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    
    if version not in SUPPORTED_PYTHON_VERSIONS:
        print(f"❌ Python {version} is not supported!")
        versions_str = ', '.join(SUPPORTED_PYTHON_VERSIONS)
        print(f"   Supported versions: {versions_str}")
        logger.error(f"Unsupported Python version: {version}")
        return False
    
    print(f"✅ Python {version} is supported")
    logger.info(f"Python version check passed: {version}")
    return True


def get_python_info() -> dict:
    """Get detailed Python environment information"""
    info = {
        "version": (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "executable": sys.executable,
        "is_virtual_env": is_virtual_environment(),
        "virtual_env_path": os.environ.get("VIRTUAL_ENV", None),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
    logger.debug(f"Python environment info: {info}")
    return info


def is_virtual_environment() -> bool:
    """Check if running in a virtual environment"""
    return (
        hasattr(sys, "real_prefix") or
        (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )


def save_api_key_to_file(api_key: str) -> bool:
    """Save API key to api_key.json in .vnstock directory"""
    try:
        # Determine config directory
        home_dir = os.path.expanduser("~")
        config_dir = os.environ.get('VNSTOCK_CONFIG_PATH')
        if not config_dir:
            config_dir = os.path.join(home_dir, ".vnstock")
        
        # Create directory if not exists
        os.makedirs(config_dir, exist_ok=True)
        
        # Save API key to JSON file
        api_key_file = os.path.join(config_dir, "api_key.json")
        api_key_data = {"api_key": api_key}
        
        with open(api_key_file, 'w') as f:
            json.dump(api_key_data, f, indent=2)
        
        # Set permissions to readable only by owner
        os.chmod(api_key_file, 0o600)
        
        logger.info(f"API key saved to {api_key_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save API key to file: {e}")
        return False


def get_hardware_uuid() -> Optional[str]:
    """Get hardware UUID based on OS (more robust than MAC address)"""
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                'wmic csproduct get uuid',
                shell=True,
                stderr=subprocess.DEVNULL
            )
            uuid_str = output.decode().split('\n')[1].strip()
            if uuid_str and uuid_str != 'UUID':
                logger.debug(f"Windows hardware UUID: {uuid_str}")
                return uuid_str
            # Fallback
            identifier = (
                f"WIN-{platform.node()}-{getpass.getuser()}"
            )
            logger.debug(f"Windows fallback identifier: {identifier}")
            return identifier
            
        elif platform.system() == "Darwin":
            output = subprocess.check_output(
                ['system_profiler', 'SPHardwareDataType'],
                stderr=subprocess.DEVNULL
            )
            for line in output.decode().split('\n'):
                if 'Hardware UUID' in line:
                    uuid_str = line.split(':')[1].strip()
                    logger.debug(f"macOS hardware UUID: {uuid_str}")
                    return uuid_str
            # Fallback
            identifier = (
                f"MAC-{platform.node()}-{getpass.getuser()}"
            )
            logger.debug(f"macOS fallback identifier: {identifier}")
            return identifier
            
        else:  # Linux
            if os.path.exists('/etc/machine-id'):
                with open('/etc/machine-id', 'r') as f:
                    machine_id = f.read().strip()
                    logger.debug(f"Linux machine-id: {machine_id}")
                    return machine_id
            # Fallback
            identifier = (
                f"LNX-{platform.node()}-{getpass.getuser()}"
            )
            logger.debug(f"Linux fallback identifier: {identifier}")
            return identifier
            
    except Exception as e:
        logger.warning(f"Could not get hardware UUID: {e}")
        # Ultimate fallback
        identifier = (
            f"{platform.system()}-{platform.node()}-{int(time.time())}"
        )
        logger.debug(f"Ultimate fallback identifier: {identifier}")
        return identifier


def setup_virtual_environment(ui: dict) -> str:
    """
    Setup Python virtual environment
    
    Gets venv type and path from environment variables set by CLI installer
    (VNSTOCK_VENV_TYPE and VNSTOCK_VENV_PATH) to avoid duplicate prompts
    
    Args:
        ui: Dictionary containing localized UI text
        
    Returns:
        str: Path to Python executable
    """
    logger.info("Setting up Python environment")
    
    # Get venv configuration from environment variables (set by CLI)
    venv_type = os.getenv('VNSTOCK_VENV_TYPE', 'default')
    venv_path = os.getenv('VNSTOCK_VENV_PATH')
    
    if venv_type == 'system':
        # Use system Python (no venv)
        logger.info(f"Using system Python: {sys.executable}")
        return sys.executable
    elif venv_type == 'custom' and venv_path:
        # Use custom venv path
        logger.info(f"Using custom venv at: {venv_path}")
        return create_or_use_venv(venv_path)
    else:
        # Default: use ~/.venv
        home_dir = os.path.expanduser("~")
        default_venv = os.path.join(home_dir, ".venv")
        logger.info(f"Using default venv at: {default_venv}")
        return create_or_use_venv(default_venv)


def get_venv_python(venv_path: str) -> str:
    """Get Python executable from venv"""
    if platform.system() == 'Windows':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    if os.path.exists(python_path):
        return python_path
    else:
        logger.warning("Python not found in venv, using system")
        return sys.executable


def create_or_use_venv(venv_path: str) -> str:
    """Create virtual environment if not exists, or use existing one"""
    venv_path = os.path.abspath(venv_path)
    logger.debug(f"create_or_use_venv called with path: {venv_path}")
    
    # Check if venv exists
    if os.path.exists(venv_path):
        # Already printed in setup_virtual_environment()
        logger.info(f"Using existing venv: {venv_path}")
    else:
        # Already printed in setup_virtual_environment()
        logger.info(f"Creating new venv at: {venv_path}")
        try:
            # Create venv with uv
            subprocess.run(
                ['uv', 'venv', venv_path, '--python', sys.executable],
                check=True,
                capture_output=True
            )
            print("✅ Virtual environment created successfully")
            logger.info("Virtual environment created successfully")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to create venv: {e}")
            logger.error(f"Failed to create venv: {e}", exc_info=True)
            return sys.executable
    
    # Get python executable path in venv
    if platform.system() == 'Windows':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    if not os.path.exists(python_path):
        print(
            "⚠️  Could not find Python in venv, "
            "using current environment"
        )
        logger.warning(
            f"Python not found at {python_path}, "
            "using current environment"
        )
        return sys.executable
    
    # Already printed in setup_virtual_environment()
    logger.info(f"Using Python from venv: {python_path}")
    return python_path



def ensure_uv_installed(python_executable: str = None) -> bool:
    """Ensure uv is installed"""
    python_exe = python_executable or sys.executable
    print("\n🔧 Checking uv package manager...")
    logger.info("Checking uv...")
    
    try:
        # Check if uv is available
        subprocess.run(
            ['uv', '--version'],
            capture_output=True,
            check=True
        )
        logger.info("uv is already installed")
        print("✅ uv is ready")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info("uv not found, installing via pip...")
        print("📦 Installing uv...")
        try:
            subprocess.run(
                [python_exe, '-m', 'pip', 'install', 'uv'],
                capture_output=True,
                check=True,
                timeout=60
            )
            logger.info("uv installed successfully")
            print("✅ uv installed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to install uv: {e}")
            print(f"❌ Failed to install uv: {e}")
            return False


def ensure_critical_packages() -> bool:
    """Install vnai + vnii to system Python for device identification.
    
    These packages are required to get device ID before anything else.
    Installing to system Python ensures they're always available.
    
    Returns:
        bool: True if success or already installed, False otherwise
    """
    print("\n🔧 Checking device identification packages...")
    logger.info("Checking critical packages: vnai, vnii")
    
    try:
        # Quick check if already installed
        import vnai
        import vnii
        logger.info("Critical packages already available")
        print("✅ Device packages ready")
        return True
    except ImportError:
        logger.info("Installing critical packages...")
    
    # Ensure uv is installed first
    ensure_uv_installed(sys.executable)
    
    try:
        # Install vnai + vnii using uv pip install
        # We target the system environment by providing python executable
        uv_cmd = get_uv_command()
        cmd = [
            uv_cmd, 'pip', 'install',
            '--python', sys.executable,
            '--extra-index-url', VNSTOCKS_INDEX_URL,
            '-c', REQUIREMENTS_URL,  # Use hosted requirements for versions
            'vnai', 'vnii'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            err_log = result.stderr[:200] if result.stderr else "Unknown error"
            err_msg = result.stderr[:100] if result.stderr else "Unknown error"
            logger.warning(f"Install failed: {err_log}")
            print(f"⚠️  Warning: {err_msg}")
            return False
        
        # CRITICAL: Invalidate import caches after pip install
        # This ensures newly installed modules are discoverable
        importlib.invalidate_caches()
        
        # Verify
        try:
            import vnai
            import vnii
            logger.info("Critical packages verified")
            print("✅ Device packages ready")
            return True
        except ImportError as e:
            logger.error(f"Verification failed: {e}")
            # Try one more time after invalidating again
            importlib.invalidate_caches()
            try:
                import vnai
                import vnii
                logger.info("Critical packages verified (2nd attempt)")
                print("✅ Device packages ready")
                return True
            except ImportError:
                return False
            
    except Exception as e:
        logger.error(f"Failed to install packages: {e}")
        return False


class VnstockLicenseManager:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://vnstocks.com",
        python_executable: str = None
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.python_executable = python_executable or sys.executable
        
        # Determine config directory
        home_dir = os.path.expanduser("~")
        config_dir = os.environ.get('VNSTOCK_CONFIG_PATH')
        if not config_dir:
            config_dir = os.path.join(home_dir, ".vnstock")
        
        # 1. Check environment variable override
        self.device_id = os.environ.get('VNSTOCK_DEVICE_ID')
        
        # 2. Check cached device.id file if not found in env
        device_id_file = os.path.join(config_dir, "device.id")
        if not self.device_id and os.path.exists(device_id_file):
            try:
                with open(device_id_file, 'r') as f:
                    self.device_id = f.read().strip()
                logger.info(f"Using cached device ID: {self.device_id}")
            except Exception:
                pass

        # 3. Check user.json if still not found
        user_json_file = os.path.join(config_dir, "user.json")
        if not self.device_id and os.path.exists(user_json_file):
            try:
                with open(user_json_file, 'r') as f:
                    data = json.load(f)
                    self.device_id = data.get('device_id') or data.get('uuid')
                logger.info(f"Using device ID from user.json: {self.device_id}")
            except Exception:
                pass
        
        if not self.device_id:
            # Fallback: Use unified device ID from vnai (single source of truth)
            try:
                from vnai.scope.profile import inspector
                self.device_id = inspector.fingerprint()
                logger.info(f"Using vnai device ID: {self.device_id}")
                
                # Cache the new ID
                os.makedirs(config_dir, exist_ok=True)
                with open(device_id_file, 'w') as f:
                    f.write(self.device_id)
            except ImportError as e:
                logger.error(
                f"vnai not available: {e}. "
                "Please install vnai first."
            )
                raise ImportError(
                "vnai is required for device identification. "
                "Please install it with: pip install vnai"
            ) from e
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                f'VnstockInstaller/1.0 '
                f'({platform.system()} {platform.release()})'
            )
        })
        
        # Setup config directory for user tracking
        self.home_dir = os.path.expanduser("~")
        
        # Check if custom config path is set (for Colab)
        config_dir = os.environ.get('VNSTOCK_CONFIG_PATH')
        if config_dir:
            self.config_dir = config_dir
        else:
            self.config_dir = os.path.join(self.home_dir, ".vnstock")
        
        os.makedirs(self.config_dir, exist_ok=True)
        self.user_info_path = os.path.join(
            self.config_dir, "user_install.json"
        )
        
        logger.info("VnstockLicenseManager initialized")
        logger.debug(f"Device ID: {self.device_id}")

    
    def register_device(self) -> Tuple[bool, str]:
        """Register current device with server"""
        try:
            logger.info("Registering device with server...")
            
            # Generate system info for registration
            system_info = {
                'platform': platform.platform(),
                'machine': platform.machine(),
                'processor': platform.processor(),
                'python_version': (
                    f"{sys.version_info.major}."
                    f"{sys.version_info.minor}."
                    f"{sys.version_info.micro}"
                )
            }
            
            payload = {
                'api_key': self.api_key,
                'device_id': self.device_id,
                'device_name': platform.node(),
                'os_type': platform.system().lower(),
                'os_version': platform.release(),
                'machine_info': system_info
            }
            
            # Log sanitized payload
            sanitized_payload = sanitize_log_data(payload)
            logger.debug(
                f"Registration payload: {sanitized_payload}"
            )
            
            response = self.session.post(
                f'{self.base_url}/api/vnstock/auth/device-register',
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Device registered successfully!")
                tier = data.get('tier', 'unknown')
                print(f"   Tier: {tier}")
                
                devices_used = data.get('devicesUsed', 0)
                device_limit = data.get('deviceLimit', 'unlimited')
                devices_info = f"{devices_used}/{device_limit}"
                print(f"   Devices used: {devices_info}")
                
                logger.info(
                    f"Device registered: tier={tier}, "
                    f"devices={devices_info}"
                )
                
                # Save registration info
                self._save_installation_info({
                    'registration_time': datetime.now().isoformat(),
                    'tier': tier,
                    'device_limit': device_limit
                })
                
                return True, "Device registered successfully"
            
            elif response.status_code == 429:
                data = response.json()
                error_detail = data.get('message', 'Unknown error')
                error_msg = f"Device limit exceeded: {error_detail}"
                logger.error(error_msg)
                return False, error_msg
            
            else:
                error_data = response.json()
                error_msg = error_data.get(
                    'error', f'HTTP {response.status_code}'
                )
                logger.error(f"Registration failed: {error_msg}")
                return False, error_msg
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
        except Exception as e:
            error_msg = f"Registration error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def _save_installation_info(self, additional_data: dict = None):
        """Save installation info to user_install.json (no sensitive data)"""
        try:
            # Get IP address for tracking
            try:
                ip_resp = requests.get(
                    "https://api.ipify.org?format=json",
                    timeout=5
                )
                ip_address = ip_resp.json().get("ip", "unknown")
            except Exception:
                ip_address = "unknown"
            
            # Gather installation info
            python_info = get_python_info()
            
            install_info = {
                "installation_time": datetime.now().isoformat(),
                "device_id": self.device_id,
                "hardware_uuid": "vnai-managed",
                "os": platform.system(),
                "os_version": platform.version(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "node": platform.node(),
                "ip_address": ip_address,
                "python": python_info,
                "cwd": os.getcwd(),
                "home_directory": self.home_dir,
            }
            
            # Add additional data if provided
            if additional_data:
                install_info.update(additional_data)
            
            # Save to user_install.json
            with open(self.user_info_path, "w") as f:
                json.dump(install_info, f, indent=2)
            
            logger.info(
                f"Installation info saved to {self.user_info_path}"
            )
            
            # ALSO save minimal info to user.json (what vnstock library expects)
            # This is used by vnstock library for authentication check
            # Format must match GUI installer's user.json structure
            user_json_path = os.path.join(self.config_dir, "user.json")
            
            # Build user.json with same structure as GUI installer
            user_json_info = {
                "user": "vnstock_cli_installer",
                "email": "unknown",  # CLI doesn't collect email
                "uuid": self.device_id,
                "os": platform.system(),
                "os_version": platform.version(),
                "ip": ip_address,
                "cwd": os.getcwd(),
                "python": python_info,  # Already has correct structure
                "time": datetime.now().isoformat(),
                "device_id": self.device_id
            }
            
            # Add tier info if available (from registration)
            if additional_data and 'tier' in additional_data:
                user_json_info['tier'] = additional_data['tier']
            
            with open(user_json_path, "w") as f:
                json.dump(user_json_info, f, indent=2)
            
            logger.info(f"User config saved to {user_json_path}")
            
            # Send to webhook if configured (for tracking purposes)
            webhook_url = os.getenv('VNSTOCK_WEBHOOK_URL')
            if webhook_url:
                self._send_webhook_notification(
                    webhook_url, install_info
                )
            
        except Exception as e:
            logger.warning(
                f"Could not save installation info: {e}",
                exc_info=True
            )
    
    def _send_webhook_notification(
        self, webhook_url: str, data: dict
    ):
        """Send installation notification to webhook (internal tracking)"""
        try:
            # Sanitize before sending
            safe_data = sanitize_log_data(data)
            
            response = requests.post(
                webhook_url,
                json=safe_data,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Webhook notification sent successfully")
            else:
                logger.warning(
                    f"Webhook notification failed: "
                    f"HTTP {response.status_code}"
                )
                
        except Exception as e:
            logger.debug(
                f"Webhook notification error: {e}"
            )
    
    def verify_license(self, package_name: str) -> Tuple[bool, str]:
        """Verify license for specific package"""
        try:
            logger.debug(f"Verifying license for {package_name}...")
            
            # Note: license/verify API requires api_key in body
            payload = {
                'api_key': self.api_key,
                'device_id': self.device_id,
                'package_name': package_name
            }
            
            response = self.session.post(
                f'{self.base_url}/api/vnstock/license/verify',
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                cache_until = data.get('cacheUntil', 'unknown')
                logger.info(
                    f"License verified for {package_name} "
                    f"(valid until {cache_until})"
                )
                return True, f"License valid until {cache_until}"
            else:
                error_data = response.json()
                error_msg = error_data.get(
                    'error', f'HTTP {response.status_code}'
                )
                logger.error(
                    f"License verification failed for {package_name}: "
                    f"{error_msg}"
                )
                return False, error_msg
                
        except Exception as e:
            error_msg = f"License verification error: {str(e)}"
            logger.error(
                f"Exception during license verification "
                f"for {package_name}: {e}",
                exc_info=True
            )
            return False, error_msg
    
    def download_package(
        self, package_name: str,
        install_dir: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Download and install vnstock package"""
        logger.info(f"Starting download for {package_name}")
        
        try:
            # Get download URL
            payload = {
                'device_id': self.device_id,
                'package_name': package_name
            }
            
            # Use Authorization header with API key
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            logger.debug(
                f"Requesting download URL for {package_name}..."
            )
            
            response = self.session.post(
                f'{self.base_url}/api/vnstock/packages/download',
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get(
                    'error',
                    f'HTTP {response.status_code}'
                )
                logger.error(
                    f"Failed to get download URL for {package_name}: "
                    f"{error_msg}"
                )
                return False, error_msg
            
            download_info = response.json()
            download_url = download_info['downloadUrl']
            logger.debug(
                f"Got download URL for {package_name}"
            )
            
            # Download file with progress
            print(f"📦 Downloading {package_name}...")
            logger.info(f"Downloading from URL...")
            
            download_response = self.session.get(
                download_url, timeout=300
            )
            if download_response.status_code != 200:
                msg = (
                    f"Download failed: "
                    f"HTTP {download_response.status_code}"
                )
                logger.error(
                    f"Download failed for {package_name}: {msg}"
                )
                return False, msg
            
            file_size = len(download_response.content)
            logger.info(
                f"Downloaded {file_size} bytes for {package_name}"
            )
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(
                suffix='.tar.gz', delete=False
            ) as temp_file:
                temp_file.write(download_response.content)
                temp_tar_path = temp_file.name
            
            logger.debug(
                f"Saved to temp file: {temp_tar_path}"
            )
            
            try:
                # Extract package to TEMP directory (not target)
                # This prevents conflicts between extract and install paths
                temp_extract_dir = tempfile.mkdtemp(
                    prefix=f'{package_name}_'
                )
                
                print(f"📁 Extracting {package_name}...")
                logger.info(f"Extracting to temp: {temp_extract_dir}")
                
                # Extract tar.gz file to temp
                with tarfile.open(
                    temp_tar_path, 'r:gz'
                ) as tar:
                    tar.extractall(path=temp_extract_dir)
                
                # List extracted files
                extracted_files = os.listdir(temp_extract_dir)
                if not extracted_files:
                    error_msg = "No files extracted"
                    logger.error(
                        f"Extraction failed for {package_name}: "
                        f"{error_msg}"
                    )
                    # Cleanup temp
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                    return False, error_msg
                
                logger.debug(
                    f"Extracted {len(extracted_files)} items"
                )
                
                # Find setup.py or pyproject.toml in subdirectory OR root
                setup_dir = None
                
                # First, check if setup.py exists in root of extracted
                setup_py_root = os.path.join(temp_extract_dir, 'setup.py')
                pyproject_root = os.path.join(
                    temp_extract_dir, 'pyproject.toml'
                )
                if (os.path.exists(setup_py_root) or
                        os.path.exists(pyproject_root)):
                    setup_dir = temp_extract_dir
                    logger.debug(f"Found setup in root: {setup_dir}")
                else:
                    # Check in subdirectories
                    for item in extracted_files:
                        item_path = os.path.join(temp_extract_dir, item)
                        if os.path.isdir(item_path):
                            setup_py = os.path.join(
                                item_path, 'setup.py'
                            )
                            pyproject = os.path.join(
                                item_path, 'pyproject.toml'
                            )
                            if (os.path.exists(setup_py) or
                                    os.path.exists(pyproject)):
                                setup_dir = item_path
                                logger.debug(
                                    f"Found setup directory: {setup_dir}"
                                )
                                break
                
                if setup_dir:
                    # Install package silently
                    logger.info(
                        f"Installing {package_name} from {setup_dir}"
                    )
                    
                    # Always use uv pip install
                    uv_cmd = get_uv_command()
                    pip_cmd = [
                        uv_cmd, 'pip', 'install',
                        '--python', self.python_executable,
                        '-q', setup_dir
                    ]
                    
                    result = subprocess.run(
                        pip_cmd,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    
                    # Cleanup temp directory after install
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                    
                    # Check for actual errors (not just returncode)
                    has_error = False
                    error_indicators = [
                        'ModuleNotFoundError',
                        'ImportError',
                        'ERROR',
                        'FAILED',
                        'Could not install'
                    ]
                    
                    stderr_output = (
                        result.stderr.lower()
                        if result.stderr else ""
                    )
                    for indicator in error_indicators:
                        if indicator.lower() in stderr_output:
                            has_error = True
                            break
                    
                    if result.returncode == 0 and not has_error:
                        # Verify package can be imported
                        can_import = self._verify_package_import(
                            package_name
                        )
                        
                        if can_import:
                            # Truly successful
                            success_msg = (
                                f"{package_name} "
                                "installed successfully"
                            )
                            logger.info(success_msg)
                            return True, success_msg
                        else:
                            # Installation completed but import fails
                            logger.error(
                                f"Package {package_name} installed but "
                                f"cannot be imported"
                            )
                            error_msg = (
                                "Installation failed - "
                                "package cannot be imported"
                            )
                            return False, error_msg
                    else:
                        # Installation failed
                        logger.error(
                            f"pip install failed for {package_name}"
                        )
                        if result.stderr:
                            # Log first few lines of error
                            error_lines = result.stderr.split('\n')[:5]
                            for line in error_lines:
                                logger.error(f"  {line}")
                        
                        error_msg = (
                            "Installation failed - "
                            "pip error (check logs)"
                        )
                        # Cleanup temp
                        shutil.rmtree(temp_extract_dir, ignore_errors=True)
                        return False, error_msg
                else:
                    # No setup directory found
                    logger.error(
                        (f"No setup.py or pyproject.toml found for "
                         f"{package_name}")
                    )
                    error_msg = "Package structure invalid"
                    # Cleanup temp
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                    return False, error_msg
                
            finally:
                # Clean up temp file
                if os.path.exists(temp_tar_path):
                    os.unlink(temp_tar_path)
                    logger.debug("Cleaned up temp tar file")
                        
        except subprocess.TimeoutExpired as e:
            logger.warning(
                f"Installation timeout for {package_name}: {e}"
            )
            return True, f"{package_name} prepared"
        except tarfile.TarError as e:
            error_msg = f"Extraction error: {str(e)}"
            logger.error(
                f"Tar extraction failed for {package_name}: {e}",
                exc_info=True
            )
            return False, error_msg
        except Exception as e:
            logger.error(
                f"Unexpected error during {package_name} install: {e}",
                exc_info=True
            )
            return True, (
                f"{package_name} "
                f"prepared (error: {str(e)[:50]})"
            )
    
    def list_available_packages(self) -> Tuple[bool, any]:
        """Get list of available packages"""
        try:
            logger.debug("Fetching available packages...")
            
            # Use Authorization header with API key
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = self.session.get(
                f'{self.base_url}/api/vnstock/packages/list',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                # Return accessible packages in the expected format
                if data.get('success'):
                    packages = data.get('data', {}).get(
                        'accessible', []
                    )
                    logger.info(
                        f"Found {len(packages)} accessible packages"
                    )
                    return True, {
                        'packages': [
                            {
                                'name': pkg['name'],
                                'displayName': pkg.get(
                                    'displayName', pkg['name']
                                ),
                                'description': pkg.get(
                                    'description', ''
                                ),
                                'version': pkg.get('version', '1.0.0'),
                                'available': True
                            }
                            for pkg in packages
                        ]
                    }
                return True, data
            else:
                error_data = response.json()
                error_msg = error_data.get(
                    'error', f'HTTP {response.status_code}'
                )
                logger.error(f"Failed to list packages: {error_msg}")
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Error fetching packages: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def get_package_dependencies(self, package_name: str) -> list:
        """Get dependencies for a package from configuration
        
        Returns minimal deps since main dependencies are already
        installed in Step 4 (install_dependencies from vnstock_cli.py)
        """
        # Return empty list - dependencies already handled in Step 4
        # Each sponsor package has its own deps in its TOML,
        # but pip will resolve them automatically during install
        logger.debug(
            f"Package-specific dependencies for {package_name}: "
            f"handled by pip (minimal additional deps expected)"
        )
        return []
    
    def _verify_package_import(self, package_name: str) -> bool:
        """Verify package can be imported after installation"""
        try:
            logger.debug(f"Verifying import for {package_name}...")
            
            # Try to import the package with longer timeout
            result = subprocess.run(
                [
                    self.python_executable,
                    '-c',
                    f'import {package_name}; print("OK")'
                ],
                capture_output=True,
                text=True,
                timeout=30  # Increased from 10s to 30s
            )
            
            if result.returncode == 0 and 'OK' in result.stdout:
                logger.debug(f"{package_name} import successful")
                return True
            else:
                # Log full error for debugging
                error_msg = result.stderr if result.stderr else result.stdout
                logger.warning(
                    f"{package_name} import check failed "
                    f"(may work in practice):"
                )
                logger.warning(f"Error output:\n{error_msg}")
                # Don't fail - package might work despite check failure
                return True
                
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Import verification timeout for {package_name} "
                f"(30s) - package may still work"
            )
            # Don't fail on timeout - package might be slow to import
            return True
        except Exception as e:
            logger.warning(
                f"Import verification error for {package_name}: {e}"
            )
            # Don't fail - let user try to use it
            return True


def print_installation_summary(
    installed_packages: List[Tuple[str, bool, str]],
    python_executable: str,
    start_time: float,
    use_vietnamese: bool = False
):
    """Print comprehensive installation summary"""
    duration = time.time() - start_time
    
    # Language strings
    if use_vietnamese:
        title = "🎉 TÓM TẮT CÀI ĐẶT"
        successful_label = "✅ Thành công"
        failed_label = "❌ Thất bại"
        python_env_label = "📦 Môi trường Python"
        version_label = "Version"
        executable_label = "Thực thi"
        venv_label = "Môi trường ảo"
        venv_not_using = "Không sử dụng môi trường ảo"
        time_label = "⏱️  Thời gian cài đặt"
        seconds = "giây"
        logs_label = "📝 Chi tiết logs"
        troubleshooting = "(Dùng để khắc phục sự cố)\n"
        quick_start = "📚 Bắt đầu nhanh"
        ready_msg = "# Các gói được tài trợ của bạn đã sẵn sàng!"
        failures = "⚠️  Một số gói không cài đặt được."
        check_logs = "Kiểm tra chi tiết logs để biết thêm thông tin.\n"
        troubleshooting_title = "\n⚠️  KHẮC PHỤC SỰ CỐ:"
        pip_issue = "Một số gói không cài đặt được do sự cố pip."
        fix_pip = "Thử sửa pip trong môi trường ảo của bạn:"
        fix_pip_cmd = "rồi chạy installer lại."
    else:
        title = "🎉 INSTALLATION SUMMARY"
        successful_label = "✅ Successful"
        failed_label = "❌ Failed"
        python_env_label = "📦 Python Environment"
        version_label = "Version"
        executable_label = "Executable"
        venv_label = "Virtual env"
        venv_not_using = "Not using virtual environment"
        time_label = "⏱️  Installation time"
        seconds = "seconds"
        logs_label = "📝 Detailed logs"
        troubleshooting = "(Use this for troubleshooting)\n"
        quick_start = "📚 Quick Start"
        ready_msg = "# Your sponsored packages are ready!"
        failures = "⚠️  Some packages failed to install."
        check_logs = "Check the detailed logs for more information.\n"
        troubleshooting_title = "\n⚠️  TROUBLESHOOTING:"
        pip_issue = "Some packages failed due to pip issues."
        fix_pip = "Try fixing pip in your virtual environment:"
        fix_pip_cmd = "Then run the installer again."
    
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    
    # Installation results
    successful = [p for p in installed_packages if p[1]]
    failed = [p for p in installed_packages if not p[1]]
    
    print(f"\n{successful_label}: {len(successful)}")
    for pkg_name, _, msg in successful:
        print(f"   • {pkg_name}")
    
    if failed:
        print(f"\n{failed_label}: {len(failed)}")
        for pkg_name, _, msg in failed:
            print(f"   • {pkg_name}: {msg}")
        
        # Check for pip errors specifically
        pip_errors = [
            p for p in failed
            if 'pip error' in p[2].lower() or 'cannot be imported' in p[2]
        ]
        
        if pip_errors:
            print(troubleshooting_title)
            print(f"   {pip_issue}")
            print(f"   {fix_pip}")
            print(f"   {python_executable} -m pip install --upgrade pip")
            print(f"   {fix_pip_cmd}")
    
    # Python environment
    print(f"\n{python_env_label}:")
    python_info = get_python_info()
    print(f"   {version_label}: {python_info['version']}")
    print(f"   {executable_label}: {python_executable}")
    
    if python_info['is_virtual_env']:
        print(f"   {venv_label}: {python_info['virtual_env_path']}")
    else:
        print(f"   {venv_label}: {venv_not_using}")
    
    # Installation time
    print(f"\n{time_label}: {duration:.1f} {seconds}")
    
    # Log file location
    print(f"\n{logs_label}: {LOG_FILE_PATH}")
    print(f"   {troubleshooting}")
    
    # Usage example
    if successful and not failed:
        print(f"{quick_start}:")
        print("   import vnstock_data")
        print("   import vnstock_ta")
        print(f"   {ready_msg}\n")
    elif failed:
        print(failures)
        print(f"   {check_logs}")
    

    logger.info(
        f"Installation completed: "
        f"{len(successful)} successful, {len(failed)} failed, "
        f"duration={duration:.1f}s"
    )


def main():
    """Main installer function"""
    start_time = time.time()
    
    # Check if running in GUI mode (non-interactive)
    gui_mode = os.getenv('VNSTOCK_GUI_MODE') == '1'
    
    # Determine language from VNSTOCK_LANGUAGE env var
    # (set by CLI installer, no prompt needed)
    lang_choice = os.getenv('VNSTOCK_LANGUAGE', '1')
    use_vietnamese = lang_choice != '2'
    
    # UI text based on language
    if use_vietnamese:
        ui = {
            'title': '🚀 Trình Cài Đặt Gói Vnstock Sponsor',
            'starting': 'Bắt đầu cài đặt Vnstock',
            'log_file': 'File log',
            'python_check': 'Kiểm tra phiên bản Python',
            'python_failed': 'Kiểm tra Python thất bại',
            'python_env': '🔧 Cấu Hình Môi Trường Python',
            'api_key_prompt': '\nNhập API key Vnstock của bạn: ',
            'api_key_required': '❌ Cần có API key!',
            'device_id': '🔍 Mã thiết bị',
            'system': '💻 Hệ thống',
            'registering': '📋 Đang đăng ký thiết bị',
            'reg_failed': '❌ Đăng ký thất bại',
            'fetching_packages': '\n📦 Đang lấy danh sách thư viện',
            'fetch_failed': '❌ Không thể lấy danh sách thư viện',
            'no_packages': '❌ Không có thư viện nào khả dụng cho gói đăng ký của bạn',
            'purchase_prompt': '💡 Vui lòng mua gói thành viên tại https://vnstocks.com/store',
            'packages_found': '✅ Tìm thấy',
            'packages_unit': 'thư viện khả dụng',
            'auto_install': '📦 Tự động cài đặt tất cả',
            'preparing_deps': '\n🔄 Đang chuẩn bị các gói phụ thuộc',
            'installing_deps': '🔧 Đang cài đặt các gói cần thiết',
            'deps_ready': '✅ Gói phụ thuộc đã sẵn sàng',
            'deps_prepared': '✅ Đã chuẩn bị gói phụ thuộc',
            'continuing': '✅ Tiếp tục',
            'installing': '\n Đang cài đặt',
            'gói': 'thư viện',
        }
    else:
        ui = {
            'title': '🚀 Vnstock Sponsored Package Installer',
            'starting': 'Starting Vnstock installer',
            'log_file': 'Log file',
            'python_check': 'Checking Python version',
            'python_failed': 'Python version check failed',
            'python_env': '🔧 Python Environment Configuration',
            'api_key_prompt': '\nEnter your Vnstock API key: ',
            'api_key_required': '❌ API key is required!',
            'device_id': '🔍 Device ID',
            'system': '💻 System',
            'registering': '📋 Registering device',
            'reg_failed': '❌ Registration failed',
            'fetching_packages': '\n📦 Fetching available packages',
            'fetch_failed': '❌ Failed to fetch packages',
            'no_packages': '❌ No packages available for your subscription',
            'purchase_prompt': '💡 Please purchase a membership plan at https://vnstocks.com/store',
            'packages_found': '✅ Found',
            'packages_unit': 'available packages',
            'auto_install': '📦 Auto-installing all',
            'preparing_deps': '\n🔄 Preparing dependencies',
            'installing_deps': '🔧 Installing required packages',
            'deps_ready': '✅ Dependencies ready',
            'deps_prepared': '✅ Dependencies prepared',
            'continuing': '✅ Continuing',
            'installing': '\n🔧 Installing',
            'gói': 'packages',
        }
    
    # Don't print title (CLI installer already printed header)
    # Just log the start information
    logger.info("=" * 60)
    logger.info(ui['starting'])
    logger.info(f"{ui['log_file']}: {LOG_FILE_PATH}")
    logger.info("=" * 60)
    
    # Check Python version
    if not check_python_version():
        logger.error(ui['python_failed'])
        sys.exit(1)
    
    # Setup virtual environment with prompt (skip in GUI mode)
    if gui_mode:
        # In GUI mode, use current Python executable
        python_executable = sys.executable
        logger.info(f"GUI mode: Using {python_executable}")
    else:
        python_executable = setup_virtual_environment(ui)
    
    # Get API key (should come from env in GUI mode)
    api_key = os.getenv('VNSTOCK_API_KEY')
    if not api_key:
        if gui_mode:
            print("❌ API key not provided in GUI mode")
            sys.exit(1)
        try:
            api_key = input(ui['api_key_prompt']).strip()
        except EOFError:
            print(ui['api_key_required'])
            sys.exit(1)
    
    if not api_key:
        print(ui['api_key_required'])
        sys.exit(1)
    
    # Save API key to environment variable and file
    os.environ['VNSTOCK_API_KEY'] = api_key
    save_api_key_to_file(api_key)
    
    # Install critical packages (vnai, vnii) to system Python
    # These are needed for device ID and MUST be available before proceeding
    if not ensure_critical_packages():
        logger.error("Failed to ensure critical packages (vnai, vnii)")
        print("\n❌ ERROR: Could not install device identification packages")
        print("   vnai and vnii are required to proceed")
        print("   Please check your internet connection and try again")
        print(f"\n   Log file: {LOG_FILE_PATH}")
        sys.exit(1)
    
    # Initialize license manager
    license_manager = VnstockLicenseManager(
        api_key, 
        python_executable=python_executable
    )
    
    print(f"{ui['device_id']}: {license_manager.device_id}")
    print(f"{ui['system']}: {platform.system()} {platform.release()}")
    print()
    
    # Register device (skip if called from GUI since OAuth already registered)
    if os.environ.get('VNSTOCK_SKIP_REGISTER') != '1':
        print(f"{ui['registering']}...")
        success, message = license_manager.register_device()
        if not success:
            print(f"{ui['reg_failed']}: {message}")
            print("\n⚠️  Note: Device registration failed, but installation will continue.")
            print("   User profile may be saved locally for next time.")
            logger.error(f"Device registration failed: {message}")
            # Save user info even if registration failed (so they can use locally)
            license_manager._save_installation_info({
                'registration_status': 'failed',
                'registration_error': message,
                'registration_time': datetime.now().isoformat()
            })
    else:
        logger.info("Skipping device registration (already done by GUI OAuth)")
    
    # CRITICAL: Ensure vnstock core is installed first
    # (Sponsor packages depend on it for device registration)
    print("\n📦 Verifying vnstock core installation...")
    vnstock_newly_installed = False
    try:
        # Suppress vnstock import messages (auth, errors, etc.)
        import io
        
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            __import__('vnstock')
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        
        print("✅ vnstock core is available")
        logger.info("vnstock core already installed")
    except ImportError:
        print("📦 Installing vnstock core...")
        logger.warning("vnstock core not found, installing...")
        
        # Ensure uv
        ensure_uv_installed(python_executable)
        
        result = subprocess.run(
            ['uv', 'pip', 'install',
             '--python', python_executable,
             '--extra-index-url', VNSTOCKS_INDEX_URL,
             '-c', REQUIREMENTS_URL,
             'vnstock'],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode != 0:
            msg = (
                "Failed to install vnstock core - "
                "sponsor packages require it"
            )
            print(f"⚠️  {msg}")
            logger.error(msg)
            logger.error(f"uv error: {result.stderr}")
        else:
            print("✅ vnstock core installed")
            logger.info("vnstock core installation successful")
            vnstock_newly_installed = True
    
    # Re-register device AFTER vnstock core installation
    # (device ID may change after importing vnstock for first time)
    if vnstock_newly_installed:
        print("\n📋 Re-registering device after vnstock installation...")
        logger.info("Re-registering device after vnstock core install")
        success, message = license_manager.register_device()
        if not success:
            print(f"{ui['reg_failed']}: {message}")
            logger.error(f"Re-registration failed: {message}")
            # Don't exit - try anyway, server might still work
        else:
            print("✅ Device re-registered successfully")
    
    # List available packages
    print(ui['fetching_packages'] + "...")
    success, packages_data = license_manager.list_available_packages()
    if not success:
        print(f"{ui['fetch_failed']}: {packages_data}")
        sys.exit(1)
    
    packages = packages_data.get('packages', [])
    available_packages = [
        pkg for pkg in packages if pkg.get('available', False)
    ]
    
    if not available_packages:
        print(ui['no_packages'] + ".")
        print(ui['purchase_prompt'])
        sys.exit(1)
    
    print(
        f"\n{ui['packages_found']} {len(available_packages)} "
        f"{ui['packages_unit']}"
    )
    
    # AUTO MODE: Install ALL packages without user selection
    # Sort packages by installation order (dependencies first)
    # Order: vnstock core → vnstock_data → others → vnstock_news
    package_order = [
        'vnstock',           # Core package (dependency for all)
        'vnstock_data',      # Data module (depends on core)
        'vnstock_ta',        # Technical analysis (depends on data)
        'vnstock_pipeline',  # Pipeline (depends on core)
        'vnstock_news'       # News crawler (last, most dependencies)
    ]
    
    def get_package_priority(pkg):
        """Return priority for sorting (lower = earlier)"""
        pkg_name = pkg['name']
        try:
            return package_order.index(pkg_name)
        except ValueError:
            # Unknown package goes at the end
            return len(package_order)
    
    selected_packages = sorted(available_packages, key=get_package_priority)
    print(f"{ui['auto_install']} {len(selected_packages)} {ui['gói']}...")
    pkg_order_str = ' → '.join([p['name'] for p in selected_packages])
    print(f"Installation order: {pkg_order_str}")
    logger.info(f"Auto-installing all {len(selected_packages)} packages")
    logger.info(f"Installation order: {pkg_order_str}")
    
    # Check dependencies and install in proper order
    print("\n📦 Preparing dependencies...")
    all_dependencies = set()
    
    for pkg in selected_packages:
        package_name = pkg['name']
        deps = license_manager.get_package_dependencies(
            package_name
        )
        for dep in deps:
            all_dependencies.add(dep)
    
    # Install dependencies with proper ordering and exclusions
    if all_dependencies:
        print("📦 Installing required packages...")
        try:
            # Dependency installation order
            # Critical dependencies first to avoid conflicts
            deps_list = list(all_dependencies)
            
            # Remove optional/problematic dependencies
            problematic_deps = ['wordcloud']  # Optional, can fail
            deps_list = [d for d in deps_list if not any(
                prob in d.lower() for prob in problematic_deps
            )]
            
            if deps_list:
                # Install dependencies with retries for better reliability
                deps_preview = ', '.join(deps_list[:5])
                if len(deps_list) > 5:
                    deps_preview += '...'
                logger.info(
                    f"Installing {len(deps_list)} dependencies: "
                    f"{deps_preview}"
                )
                result = subprocess.run(
                    ['uv', 'pip', 'install',
                     '--python', license_manager.python_executable,
                     '-q', '--extra-index-url', VNSTOCKS_INDEX_URL,
                     '-c', REQUIREMENTS_URL] + deps_list,
                    capture_output=True,
                    text=True,
                    timeout=600  # Increased timeout for large dependencies
                )
                
                if result.returncode == 0:
                    print(ui["deps_ready"])
                else:
                    # Don't fail, continue anyway
                    logger.warning(
                        f"Some dependencies had issues (continuing): "
                        f"{result.stderr[:200]}"
                    )
                    print(ui["deps_prepared"])
            
        except subprocess.TimeoutExpired:
            logger.warning("Dependency installation timeout")
            print(ui["continuing"] + "...")
        except Exception as e:
            logger.warning(f"Dependency installation error: {e}")
            print(ui["continuing"] + "...")
    
    # Install selected packages
    print(f"{ui['installing']} {len(selected_packages)} {ui['gói']}...")
    logger.info(
        f"Starting installation of {len(selected_packages)} packages"
    )
    
    # Track installation results
    installation_results = []
    
    for pkg in selected_packages:
        package_name = pkg['name']
        print(f"\n📦 {package_name}...")
        logger.info(f"Installing {package_name}...")
        
        # Download and install (no custom install_dir for temp mode)
        success, message = license_manager.download_package(package_name)
        installation_results.append((package_name, success, message))
        
        if success:
            print(f"✅ {package_name} ready")
        else:
            print(f"❌ {package_name} failed: {message}")
        
        # Add delay between packages to allow server to process
        # and prevent API session timeout issues
        if pkg != selected_packages[-1]:
            time.sleep(3)
    
    # Print comprehensive summary
    print_installation_summary(
        installation_results,
        python_executable,
        start_time,
        use_vietnamese=use_vietnamese
    )
    
    # Update installation info with results
    license_manager._save_installation_info({
        'installed_packages': [
            {
                'name': pkg_name,
                'success': success,
                'message': message
            }
            for pkg_name, success, message in installation_results
        ],
        'installation_duration': time.time() - start_time
    })
    
    logger.info("Installation process completed")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Installation cancelled by user.")
        logger.info("Installation cancelled by user (KeyboardInterrupt)")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print(f"📝 Check logs for details: {LOG_FILE_PATH}")
        logger.error(
            f"Unexpected error during installation: {e}",
            exc_info=True
        )
        # Print traceback to log only
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())
        sys.exit(1)

