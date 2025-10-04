# Revisor de Código con IA

Revisor de Código con IA es un script de Python que utiliza GPT-3.5-turbo de OpenAI para revisar automáticamente cambios de código en repositorios de GitLab. Escucha eventos de merge request y push, obtiene los cambios de código asociados y proporciona retroalimentación sobre los cambios en formato Markdown.

## Características

- Revisa automáticamente cambios de código en repositorios de GitLab
- Proporciona retroalimentación sobre claridad del código, simplicidad, bugs y problemas de seguridad
- Genera respuestas en formato Markdown para fácil lectura en GitLab
- **Logging extensivo para debugging**
- **Prompts completamente en español**
- **Validación de configuración al inicio**
- **Endpoint de health check para monitoreo**

## Inicio Rápido

### Prerrequisitos

- Python 3.8 o superior
- Docker (opcional)
- Una clave API de OpenAI
- Un token API de GitLab

### Instalación

1. Clona el repositorio:
```bash
git clone https://git.facha.dev/facha/openai-gitlab-pr-review.git
cd openai-gitlab-pr-review
```

2. Instala los paquetes de Python requeridos:
```bash
pip install -r requirements.txt
```

3. Configura las variables de entorno:
```bash
# Copia el archivo de ejemplo
cp config.example .env

# Edita el archivo .env con tus credenciales
nano .env
```

Variables de entorno requeridas:
```bash
OPENAI_API_KEY=tu_clave_de_openai_aqui
GITLAB_TOKEN=tu_token_de_gitlab_aqui
GITLAB_URL=https://gitlab.com/api/v4
EXPECTED_GITLAB_TOKEN=tu_token_esperado_para_webhooks
```

4. Ejecuta la aplicación:
```bash
python main.py
```

### Debugging

La aplicación incluye logging extensivo para facilitar el debugging:

1. **Logs en consola y archivo**: Los logs se guardan en `app.log` y se muestran en consola
2. **Health check**: Visita `http://localhost:8080/health` para verificar el estado de la configuración
3. **Endpoint raíz**: Visita `http://localhost:8080/` para información básica

#### Verificar configuración:
```bash
curl http://localhost:8080/health
```

#### Ver logs en tiempo real:
```bash
tail -f app.log
```


### Docker

Alternativamente, puedes usar Docker para ejecutar la aplicación:

1. Construye la imagen de Docker:
```bash
docker-compose build
```

2. Ejecuta el contenedor de Docker:
```bash
docker-compose up -d
```

## Uso

1. Configura tu repositorio de GitLab para enviar eventos de webhook a la aplicación Revisor de Código con IA siguiendo la [documentación de webhooks de GitLab](https://docs.gitlab.com/ee/user/project/integrations/webhooks.html).

2. La aplicación Revisor de Código con IA revisará automáticamente los cambios de código en tu repositorio de GitLab y proporcionará retroalimentación como comentarios en merge requests y diffs de commits.

## Solución de Problemas

### La aplicación no responde a webhooks

1. **Verifica la configuración**:
   ```bash
   curl http://localhost:8080/health
   ```

2. **Revisa los logs**:
   ```bash
   tail -f app.log
   ```

3. **Verifica las variables de entorno**:
   - Asegúrate de que todas las variables estén configuradas
   - Verifica que los tokens sean correctos

### Errores comunes

- **"Variables de entorno faltantes"**: Configura todas las variables requeridas
- **"Token de GitLab no válido"**: Verifica que `EXPECTED_GITLAB_TOKEN` coincida con el configurado en GitLab
- **"Error al obtener cambios del MR"**: Verifica que `GITLAB_TOKEN` tenga permisos de lectura
- **"Error al llamar a OpenAI"**: Verifica que `OPENAI_API_KEY` sea válida y tenga créditos
