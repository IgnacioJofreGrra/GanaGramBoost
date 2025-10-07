import os
from typing import Optional
from sys import platform

from selenium import webdriver  # type: ignore
from selenium.webdriver.chrome.service import Service  # type: ignore
from webdriver_manager.chrome import ChromeDriverManager  # type: ignore


class Browser:
    def __init__(self, window: bool = True, binary_location: Optional[str] = None, default_lang: bool = False, **kwargs):

        # Configurar opciones de Chrome
        options = webdriver.ChromeOptions()

        if not default_lang:
            options.add_experimental_option('prefs', {'intl.accept_languages': 'en,en_US'})

        # Headless si window=False
        if not window:
            options.add_argument('--headless=new')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')

        # Permitir especificar la ubicación del binario de Chrome si el usuario lo define
        if binary_location:
            options.binary_location = binary_location

        # Por defecto usar webdriver-manager para gestionar el ChromeDriver.
        # Solo usar el binario local en 'drivers/' si se pasa use_local_driver=True.
        use_local_driver: bool = kwargs.get('use_local_driver', False)
        service: Service
        if use_local_driver:
            driver_path = None
            drivers_dir = os.path.join(os.getcwd(), 'drivers')
            if os.path.isdir(drivers_dir):
                if platform in ('linux', 'linux2'):
                    candidate = os.path.join(drivers_dir, 'chrome_linux')
                elif platform == 'win32':
                    candidate = os.path.join(drivers_dir, 'chrome_windows.exe')
                elif platform == 'darwin':
                    candidate = os.path.join(drivers_dir, 'chrome_mac')
                else:
                    candidate = None

                if candidate and os.path.exists(candidate):
                    try:
                        os.chmod(candidate, 0o755)
                    except Exception:
                        pass
                    driver_path = candidate

            if driver_path:
                service = Service(driver_path)
            else:
                service = Service(ChromeDriverManager().install())
        else:
            service = Service(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=options)


class Tab:
    def __init__(self, driver: webdriver.Chrome, url: str):
        self.driver = driver
        self.url = url

    def new_tab(self, url: str = 'https://www.google.com'):
        """Abre una nueva pestaña en el navegador y navega hacia la URL indicada."""

        self.driver.execute_script(f"window.open('{url}');")
        self.driver.switch_to.window(self.driver.window_handles[-1])

    def close_tab(self):
        """Cierra la pestaña actual y regresa a la pestaña previa."""

        self.driver.close()
        self.driver.switch_to.window(self.driver.window_handles[-1])  # preferimos usar el último handle disponible

    def __enter__(self):
        self.new_tab(self.url)

    def __exit__(self, *exc):
        self.close_tab()
