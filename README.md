# yt-autoshorts

Publica un YouTube Short diario generado íntegramente con IA, con coste ~0 €.

Pipeline: **Gemini** (guion) → **edge-tts** (voz + tiempos por palabra) → **Pexels** (clips verticales)
→ **ffmpeg** (montaje 1080x1920 + subtítulos) → **YouTube Data API** (subida) → **GitHub Actions** (cron diario).

## Puesta en marcha (una sola vez)

1. **Gemini**: crea una API key gratis en https://aistudio.google.com/apikey
2. **Pexels**: crea una API key gratis en https://www.pexels.com/api/
3. **YouTube**:
   1. En https://console.cloud.google.com crea un proyecto y habilita *YouTube Data API v3*.
   2. *Pantalla de consentimiento OAuth* → tipo *Externo*, añade tu cuenta como usuario de prueba
      y **publica la app** ("En producción"); si se queda en "Prueba" el refresh token caduca a los 7 días.
   3. *Credenciales* → *ID de cliente OAuth* → tipo *App de escritorio* → descarga el JSON como
      `client_secret.json` en la raíz del proyecto.
   4. Ejecuta en local y autoriza con la cuenta del canal:
      ```bash
      python -m venv .venv && .venv/bin/pip install -r requirements.txt
      .venv/bin/python scripts/get_token.py   # abre la URL que imprime y autoriza
      gh secret set -f .yt.env
      ```
4. Sube el proyecto a un repo de GitHub y añade en *Settings → Secrets and variables → Actions*:
   `GEMINI_API_KEY`, `PEXELS_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
5. Lanza *Actions → Daily Short → Run workflow* para probar. Después se ejecuta solo cada día a las 16:00 UTC.

> ⚠️ Los proyectos de API sin auditar suben los vídeos como **privados**. Solicita la auditoría
> (formulario *YouTube API Services - Audit and Quota Extension*) para que se publiquen en público.

## Probar en local sin subir

Requiere `ffmpeg` instalado.

```bash
export GEMINI_API_KEY=... PEXELS_API_KEY=...
.venv/bin/python main.py --no-upload   # resultado en build/short.mp4
```

## Personalizar

Todo en `config.yaml`: nicho, idioma, voz (`edge-tts --list-voices`), longitud, nº de clips y privacidad.
`history.json` guarda los temas publicados para no repetirlos (el workflow lo commitea tras cada subida).

## Coste

| Servicio | Coste |
|---|---|
| Gemini Flash (capa gratuita, con modelos de respaldo en `config.yaml`) | 0 € |
| edge-tts | 0 € |
| Pexels | 0 € |
| YouTube Data API (1.600 de 10.000 unidades/día) | 0 € |
| GitHub Actions (~3-5 min/día) | 0 € en repo público; en privado entra en los 2.000 min/mes gratis |
