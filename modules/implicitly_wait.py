from contextlib import contextmanager

from selenium import webdriver  # type: ignore


class ImplicitlyWait:
    def __init__(self, driver: webdriver, timeout: int):
        self.driver = driver
        self.timeout = timeout

    def enable(self) -> None:
        """Activa la espera implícita para permitir que los elementos aparezcan."""

        self.driver.implicitly_wait(self.timeout)

    def disable(self) -> None:
        """Desactiva la espera implícita para evitar demoras innecesarias."""

        self.driver.implicitly_wait(0)

    @contextmanager
    def ignore(self):
        """Deshabilita temporalmente la espera implícita dentro del bloque gestionado."""

        try:
            yield self.disable()
        finally:
            self.enable()
