# yt-autoshorts

Publica un YouTube Short diario generado íntegramente con IA, con coste ~0 €.

Pipeline: **Gemini** (guion dividido en escenas) → **edge-tts** (voz + tiempos por palabra)
→ **Wikipedia / Wikimedia Commons / Pexels** (candidatos por escena; Gemini elige el que muestra lo narrado)
→ **ffmpeg** (montaje 1080x1920, cada visual sincronizado con su frase, + subtítulos) → **YouTube Data API** (subida) → **GitHub Actions** (cron diario).

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
5. Lanza *Actions → Daily Short → Run workflow* para probar. Después se ejecuta solo cada día a las 11:00, 16:00 y 19:00 UTC.

> ⚠️ Los proyectos de API sin auditar suben los vídeos como **privados**. Solicita la auditoría
> (formulario *YouTube API Services - Audit and Quota Extension*) para que se publiquen en público.

## Publicación en oculto y paso a público

Cada short se sube en **oculto** (`upload.privacy: "unlisted"`) para que YouTube lo analice antes de enseñarlo, y
`.github/workflows/publish.yml` lo pasa a **público al día siguiente**, en la misma franja en que se subió
(11:00, 16:00 y 19:00 UTC). `publish.py` publica los shorts de `history.json` que llevan al menos `publish.after_hours`
(22 h) en oculto y ya están procesados; no guarda estado, así que si una ejecución falla los publica la siguiente.

- Ajusta los cron de `publish.yml` a las horas en que tu audiencia está conectada (Studio → Estadísticas → Audiencia →
  *Cuándo están conectados tus espectadores*).
- Si quieres que un short no se publique, pásalo a **privado** en Studio: solo se tocan los que siguen en oculto.
- Requiere el scope `youtube.force-ssl` en el token. Si falta, los shorts se suben directamente en público (comportamiento
  anterior) y el log lo avisa. Para activarlo: `.venv/bin/python scripts/get_token.py` y `gh secret set -f .yt.env`.
- `.venv/bin/python publish.py --dry-run` muestra qué se publicaría sin cambiar nada.

Además, en cada subida: contenido sintético declarado, "no es para niños", idioma `es`, contador de "me gusta" visible,
máximo 5 hashtags (los del tema primero) y el short se añade a la lista de reproducción de su temática (`playlists` en
`config.yaml`; Gemini elige una y la lista se crea pública si no existe) para encadenar visualizaciones.
Las pantallas finales y tarjetas no existen en los Shorts ni en la API.

## Facebook Reels (opcional)

Si existen los secrets `FB_PAGE_ID` y `FB_PAGE_TOKEN`, cada short se publica también como Reel en la página de
Facebook. Si faltan o Facebook falla, YouTube sigue funcionando igual.

1. Crea una **página** de Facebook para el canal.
2. En https://developers.facebook.com crea una app de tipo *Empresa*.
3. En *Graph API Explorer* elige la app, genera un *User Token* con los permisos `pages_show_list`,
   `pages_read_engagement`, `pages_manage_posts` y `publish_video`, y autoriza la página.
4. Ejecuta `.venv/bin/python scripts/get_fb_token.py` (pide App ID, App secret y el token) y después
   `gh secret set -f .fb.env`. El token de página resultante no caduca.

## Instagram Reels (opcional)

Si existe el secret `IG_USER_ID`, cada short se publica también como Reel en Instagram usando el mismo token de la
página de Facebook.

1. Convierte la cuenta de Instagram en **profesional** (creador o empresa) y vincúlala a la página de Facebook.
2. Añade a la app el caso de uso de Instagram y, en *Graph API Explorer*, genera el *User Token* con los permisos de
   Facebook anteriores más `instagram_basic` e `instagram_content_publish`.
3. Ejecuta de nuevo `scripts/get_fb_token.py`: ahora `.fb.env` incluye `IG_USER_ID`. Súbelo con
   `gh secret set -f .fb.env`.

## TikTok (opcional)

Si existen `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` y `TIKTOK_REFRESH_TOKEN`, cada short se publica también en
TikTok mediante la Content Posting API (marcado como contenido generado por IA).

1. En https://developers.tiktok.com crea una app con los productos *Login Kit* y *Content Posting API* (con
   *Direct Post* activado), el scope `video.publish` y una redirect URI propia.
2. Ejecuta `.venv/bin/python scripts/get_tiktok_token.py`, autoriza tu cuenta y sube `gh secret set -f .tiktok.env`.
   El refresh token dura un año.
3. Mientras TikTok no audite la app, solo se puede publicar si la **cuenta de TikTok es privada** (error
   `unaudited_client_can_only_post_to_private_accounts`), y los vídeos quedan como `SELF_ONLY`. Tras la auditoría,
   vuelve a poner la cuenta pública: se publicará en público (configurable con `TIKTOK_PRIVACY_LEVEL`).
4. Las credenciales actuales son del **sandbox** de la app; al aprobarse la auditoría hay que repetir el paso 2 con el
   client key/secret de producción.

## Probar en local sin subir

Requiere `ffmpeg` instalado.

```bash
export GEMINI_API_KEY=... PEXELS_API_KEY=...
.venv/bin/python main.py --no-upload   # resultado en build/short.mp4
```

## Personalizar

Todo en `config.yaml`: nicho, idioma, voz (`edge-tts --list-voices`), longitud, nº de escenas y privacidad.
`history.json` guarda los temas publicados para no repetirlos (el workflow lo commitea tras cada subida).

## Coste

| Servicio | Coste |
|---|---|
| Gemini Flash (capa gratuita, con modelos de respaldo en `config.yaml`) | 0 € |
| edge-tts | 0 € |
| Pexels | 0 € |
| YouTube Data API (1.600 de 10.000 unidades/día) | 0 € |
| GitHub Actions (~3-5 min/día) | 0 € en repo público; en privado entra en los 2.000 min/mes gratis |

## Música de fondo

Pon pistas sin copyright (`.mp3`, `.m4a`, `.wav`, `.ogg`) en `music/` y haz commit. Cada vídeo elige una al azar
y la mezcla a volumen bajo (`music.volume` en `config.yaml`). Si la carpeta está vacía, el vídeo sale solo con voz.
Fuente recomendada: Biblioteca de audio de YouTube Studio, filtrando por "No se requiere atribución".
