# GanaGramBoost

![GitHub top language](https://img.shields.io/github/languages/top/IgnacioJofreGrra/GanaGramBoost?style=for-the-badge)
![GitHub tag (latest by date)](https://img.shields.io/github/v/tag/IgnacioJofreGrra/GanaGramBoost?style=for-the-badge)
![GitHub last commit](https://img.shields.io/github/last-commit/IgnacioJofreGrra/GanaGramBoost?style=for-the-badge)

<p>
	<a href="https://www.buymeacoffee.com/IgnacioJofreGrra" target="_blank" rel="noopener noreferrer">
		<img src="https://media.giphy.com/media/7kZE0z52Sd9zSESzDA/giphy.gif" alt="Invítame un café" width="220">
	</a>
</p>

##### Bot de Instagram que envía menciones en tus publicaciones favoritas para **aumentar tus probabilidades de ganar un sorteo de Instagram**.

## ¿Cómo funciona este bot?
Simula la interacción de un navegador mediante Selenium. **Probado en Windows.**

Al comenzar ejecuta hasta cuatro pasos automáticos (los datos quedan guardados para reutilizarlos y ahorrar tiempo):

1. Inicio de sesión.
2. Identificación del dueño de la publicación.
3. Búsqueda y almacenamiento de seguidores o seguidos.
4. Envío de comentarios con menciones en la publicación objetivo.

## Gestión del driver de Chrome
El proyecto utiliza `webdriver-manager` para descargar de forma automática la versión adecuada de ChromeDriver según el navegador que tengas instalado. No necesitas gestionar el driver manualmente. Si aun así prefieres usar un binario local, colócalo en `drivers/` y activa el parámetro `use_local_driver=True` al crear el `Bot` (ya previsto internamente).

## Requisitos previos
- Google Chrome actualizado (versión estable más reciente).
- Python 3.9 o superior instalado y disponible en la variable de entorno `PATH`.
- PowerShell para ejecutar los comandos sugeridos en Windows.

## Instalación rápida
1. (Opcional) Crea y activa un entorno virtual en PowerShell dentro de la carpeta del repositorio.
2. Instala las dependencias especificadas en `requirements.txt`.
3. Edita `config.ini` con tus credenciales y preferencias.
4. Ejecuta `script.py` desde el mismo entorno virtual.

### Comandos de referencia (PowerShell)
```powershell
python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" script.py
```

> Ajusta las rutas si tu entorno virtual se encuentra en otra ubicación o si utilizas `py`/`python3` en lugar de `python`.

## Configuración (`config.ini`)
Todas las credenciales y ajustes del bot se controlan desde `config.ini`.

- **[Required]**: credenciales de Instagram, enlace de la publicación y mensaje (expresión) de comentarios.
- **[Optional]**: parámetros adicionales como usuario objetivo, límite de resultados, uso de archivos personalizados o modo "solo guardar".
- **[Interval]**: controla el intervalo aleatorio entre comentarios (mínimo, máximo y peso).
- **[Browser]**: opciones del navegador (ventana visible, idioma, ubicación del ejecutable y tiempo de espera).

Consulta los comentarios dentro del archivo (ahora en español) para entender cada ajuste.

## Modo "Save Only"
Activa `Save Only = True` en `[Optional]` para almacenar seguidores/seguidos sin publicar comentarios. Esta modalidad es ideal si deseas preparar un archivo de menciones y comentar más tarde.

## Consejos y advertencias
- Usa una cuenta secundaria si temes que Instagram restrinja tu perfil principal.
- Instagram limita la frecuencia de comentarios; ajusta los intervalos si recibes avisos de bloqueo temporal.
- Puedes interrumpir el proceso con `Ctrl + C`. El bot guardará el progreso antes de salir.
- Mantén Chrome actualizado para reducir incompatibilidades con ChromeDriver.

## Créditos
Proyecto adaptado, actualizado y traducido completamente al español por **IgnacioJofreGrra**.
