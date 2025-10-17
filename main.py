import os
import json
import requests
import logging
from flask import Flask, request
import openai

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Validación de variables de entorno
def validate_environment():
    """Valida que todas las variables de entorno necesarias estén configuradas"""
    required_vars = ["OPENAI_API_KEY", "GITLAB_TOKEN", "GITLAB_URL", "EXPECTED_GITLAB_TOKEN"]
    missing_vars = []
    
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Variables de entorno faltantes: {missing_vars}")
        raise ValueError(f"Faltan las siguientes variables de entorno: {', '.join(missing_vars)}")
    
    logger.info("Todas las variables de entorno están configuradas correctamente")

# Configuración de OpenAI
openai.api_key = os.environ.get("OPENAI_API_KEY")
gitlab_token = os.environ.get("GITLAB_TOKEN")
gitlab_url = os.environ.get("GITLAB_URL")

api_base = os.environ.get("AZURE_OPENAI_API_BASE")
if api_base is not None:
    openai.api_base = api_base
    logger.info(f"Usando Azure OpenAI con base URL: {api_base}")

openai.api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
if openai.api_version is not None:
    openai.api_type = "azure"
    logger.info(f"Configurado para usar Azure OpenAI con versión: {openai.api_version}")

# Validar configuración al inicio
try:
    validate_environment()
except ValueError as e:
    logger.error(f"Error de configuración: {e}")
    exit(1)

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("=== NUEVO WEBHOOK RECIBIDO ===")
    logger.info(f"Headers recibidos: {dict(request.headers)}")
    logger.info(f"Content-Type: {request.content_type}")
    logger.info(f"Content-Length: {request.content_length}")
    
    # Validar token de GitLab
    received_token = request.headers.get("X-Gitlab-Token")
    expected_token = os.environ.get("EXPECTED_GITLAB_TOKEN")
    
    logger.info(f"Token recibido: {received_token[:10]}..." if received_token else "No token recibido")
    logger.info(f"Token esperado: {expected_token[:10]}..." if expected_token else "No token esperado configurado")
    
    if received_token != expected_token:
        logger.warning("Token de GitLab no válido - acceso denegado")
        return "No autorizado", 403
    
    try:
        payload = request.json
        logger.info(f"Payload recibido: {json.dumps(payload, indent=2)}")
    except Exception as e:
        logger.error(f"Error al parsear JSON del payload: {e}")
        return "Error en el payload JSON", 400
    
    if not payload:
        logger.warning("Payload vacío recibido")
        return "Payload vacío", 400
    
    object_kind = payload.get("object_kind")
    logger.info(f"Tipo de evento: {object_kind}")
    
    if object_kind == "merge_request":
        logger.info("Procesando evento de Merge Request")
        return process_merge_request(payload)
    elif object_kind == "push":
        logger.info("Procesando evento de Push")
        return process_push_event(payload)
    else:
        logger.warning(f"Tipo de evento no soportado: {object_kind}")
        return f"Tipo de evento no soportado: {object_kind}", 200

def process_merge_request(payload):
    """Procesa eventos de Merge Request"""
    try:
        action = payload["object_attributes"]["action"]
        logger.info(f"Acción del MR: {action}")
        
        if action != "open":
            logger.info(f"MR no es de apertura (acción: {action}), ignorando")
            return "No es un MR de apertura", 200
        
        project_id = payload["project"]["id"]
        mr_id = payload["object_attributes"]["iid"]
        project_name = payload["project"]["name"]
        
        logger.info(f"Procesando MR #{mr_id} del proyecto {project_name} (ID: {project_id})")
        
        changes_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/changes"
        logger.info(f"URL de cambios: {changes_url}")

        headers = {"Private-Token": gitlab_token}
        logger.info("Obteniendo cambios del MR desde GitLab...")
        
        response = requests.get(changes_url, headers=headers)
        logger.info(f"Respuesta de GitLab - Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Error al obtener cambios del MR: {response.status_code} - {response.text}")
            return f"Error al obtener cambios del MR: {response.status_code}", 500
        
        mr_changes = response.json()
        logger.info(f"Cambios obtenidos: {len(mr_changes.get('changes', []))} archivos modificados")
        
        diffs = [change["diff"] for change in mr_changes["changes"]]
        logger.info(f"Total de diffs: {len(diffs)}")
        
        # Prompt en español
        pre_prompt = "Revisa los siguientes cambios de código git diff, enfocándote en estructura, seguridad, claridad, arquitectura hexagonal, separación de responsabilidades y orientación a objetos."

        questions = """
        Preguntas:
        1. Resume los cambios principales.
        2. ¿Es claro el código nuevo/modificado?
        3. ¿Son descriptivos los comentarios y nombres?
        4. ¿Se puede reducir la complejidad? ¿Ejemplos?
        5. ¿Algún bug? ¿Dónde?
        6. ¿Problemas de seguridad potenciales?
        7. ¿Los cambios respetan la arquitectura hexagonal (puertos y adaptadores)?
        8. ¿Hay una adecuada separación de incumbencias (responsabilidades)?
        9. ¿El código está bien orientado a objetos (encapsulación, herencia, polimorfismo)?
        10. ¿Sugerencias para alineación con mejores prácticas?
        """

        messages = [
            {"role": "system", "content": "Eres un desarrollador senior especializado en arquitectura de software, revisando cambios de código con enfoque en arquitectura hexagonal, separación de responsabilidades, orientación a objetos y mejores prácticas de desarrollo."},
            {"role": "user", "content": f"{pre_prompt}\n\n{''.join(diffs)}{questions}"},
            {"role": "assistant", "content": "Responde en markdown compatible con GitLab. Incluye una versión concisa de cada pregunta en tu respuesta, prestando especial atención a los aspectos arquitectónicos y de diseño."},
        ]

        logger.info("Enviando solicitud a OpenAI...")
        logger.info(f"Modelo a usar: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
        
        try:
            client = openai.OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                base_url="https://api.groq.com/openai/v1"
            )
            response = client.responses.create(
                model="llama-3.1-8b-instant",
                input='\n\n'.join([message["content"] for message in messages]),
            )
            logger.info("Respuesta de OpenAI recibida exitosamente")
            logger.info(f"Metricas: {response.usage}")
            answer = response.output_text.strip()
            answer += "\n\nEste comentario fue generado por un pato de inteligencia artificial."
        except Exception as e:
            logger.error(f"Error al llamar a OpenAI: {e}")
            answer = "Lo siento, no me siento bien hoy. Por favor, pide a un humano que revise este PR."
            answer += "\n\nEste comentario fue generado por un pato de inteligencia artificial."
            answer += f"\n\nError: {str(e)}"

        logger.info(f"Respuesta generada (longitud: {len(answer)} caracteres)")
        logger.info(f"Respuesta: {answer[:200]}...")
        
        comment_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_id}/notes"
        comment_payload = {"body": answer}
        
        logger.info(f"Enviando comentario a: {comment_url}")
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)
        
        logger.info(f"Respuesta del comentario - Status: {comment_response.status_code}")
        if comment_response.status_code != 201:
            logger.error(f"Error al enviar comentario: {comment_response.text}")
        else:
            logger.info("Comentario enviado exitosamente al MR")
            
        return "OK", 200
        
    except KeyError as e:
        logger.error(f"Campo faltante en el payload del MR: {e}")
        return f"Campo faltante en el payload: {e}", 400
    except Exception as e:
        logger.error(f"Error inesperado procesando MR: {e}")
        return f"Error procesando MR: {e}", 500
def process_push_event(payload):
    """Procesa eventos de Push"""
    try:
        project_id = payload["project_id"]
        commit_id = payload["after"]
        project_name = payload.get("project", {}).get("name", "Proyecto desconocido")
        
        logger.info(f"Procesando push del proyecto {project_name} (ID: {project_id})")
        logger.info(f"Commit ID: {commit_id}")
        
        commit_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/diff"
        logger.info(f"URL de diff del commit: {commit_url}")

        headers = {"Private-Token": gitlab_token}
        logger.info("Obteniendo diff del commit desde GitLab...")
        
        response = requests.get(commit_url, headers=headers)
        logger.info(f"Respuesta de GitLab - Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Error al obtener diff del commit: {response.status_code} - {response.text}")
            return f"Error al obtener diff del commit: {response.status_code}", 500
        
        changes = response.json()
        logger.info(f"Cambios obtenidos: {len(changes)} archivos modificados")

        changes_string = ''.join([str(change) for change in changes])
        logger.info(f"Longitud del diff: {len(changes_string)} caracteres")

        # Prompt en español
        pre_prompt = "Revisa el git diff de un commit reciente, enfocándote en claridad, estructura, seguridad, arquitectura hexagonal, separación de responsabilidades y orientación a objetos."

        questions = """
        Preguntas:
        1. Resume los cambios (estilo Changelog).
        2. ¿Claridad del código agregado/modificado?
        3. ¿Adecuación de comentarios y nombres?
        4. ¿Simplificación sin romper funcionalidad? ¿Ejemplos?
        5. ¿Algún bug? ¿Dónde?
        6. ¿Problemas de seguridad potenciales?
        7. ¿Los cambios respetan la arquitectura hexagonal (puertos y adaptadores)?
        8. ¿Hay una adecuada separación de incumbencias (responsabilidades)?
        9. ¿El código está bien orientado a objetos (encapsulación, herencia, polimorfismo)?
        """

        messages = [
            {"role": "system", "content": "Eres un desarrollador senior especializado en arquitectura de software, revisando cambios de código de un commit con enfoque en arquitectura hexagonal, separación de responsabilidades, orientación a objetos y mejores prácticas de desarrollo."},
            {"role": "user", "content": f"{pre_prompt}\n\n{changes_string}{questions}"},
            {"role": "assistant", "content": "Responde en markdown para GitLab. Incluye versiones concisas de las preguntas en la respuesta, prestando especial atención a los aspectos arquitectónicos y de diseño."},
        ]

        logger.info("Enviando solicitud a OpenAI para revisión de commit...")
        logger.info(f"Modelo a usar: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
        
        try:
            completions = openai.ChatCompletion.create(
                deployment_id=os.environ.get("OPENAI_API_MODEL"),
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                temperature=0.7,
                stream=False,
                messages=messages
            )
            logger.info("Respuesta de OpenAI recibida exitosamente")
            answer = completions.choices[0].message["content"].strip()
            answer += "\n\nPara referencia, me dieron las siguientes preguntas: \n"
            for question in questions.split("\n"):
                answer += f"\n{question}"
            answer += "\n\nEste comentario fue generado por un pato de inteligencia artificial."
        except Exception as e:
            logger.error(f"Error al llamar a OpenAI: {e}")
            answer = "Lo siento, no me siento bien hoy. Por favor, pide a un humano que revise este cambio de código."
            answer += "\n\nEste comentario fue generado por un pato de inteligencia artificial."
            answer += f"\n\nError: {str(e)}"

        logger.info(f"Respuesta generada (longitud: {len(answer)} caracteres)")
        logger.info(f"Respuesta: {answer[:200]}...")
        
        comment_url = f"{gitlab_url}/projects/{project_id}/repository/commits/{commit_id}/comments"
        comment_payload = {"note": answer}
        
        logger.info(f"Enviando comentario a: {comment_url}")
        comment_response = requests.post(comment_url, headers=headers, json=comment_payload)
        
        logger.info(f"Respuesta del comentario - Status: {comment_response.status_code}")
        if comment_response.status_code != 201:
            logger.error(f"Error al enviar comentario: {comment_response.text}")
        else:
            logger.info("Comentario enviado exitosamente al commit")
            
        return "OK", 200
        
    except KeyError as e:
        logger.error(f"Campo faltante en el payload del push: {e}")
        return f"Campo faltante en el payload: {e}", 400
    except Exception as e:
        logger.error(f"Error inesperado procesando push: {e}")
        return f"Error procesando push: {e}", 500

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de health check para verificar el estado de la aplicación"""
    logger.info("Health check solicitado")
    
    status = {
        "status": "healthy",
        "openai_configured": bool(openai.api_key),
        "gitlab_configured": bool(gitlab_token and gitlab_url),
        "expected_token_configured": bool(os.environ.get("EXPECTED_GITLAB_TOKEN")),
        "azure_configured": bool(os.environ.get("AZURE_OPENAI_API_BASE"))
    }
    
    all_configured = all(status.values())
    if not all_configured:
        status["status"] = "unhealthy"
        logger.warning("Health check fallido - configuración incompleta")
    
    return json.dumps(status, indent=2), 200 if all_configured else 500

@app.route('/', methods=['GET'])
def root():
    """Endpoint raíz con información básica"""
    logger.info("Solicitud al endpoint raíz")
    return """
    <h1>Revisor de Código con IA</h1>
    <p>Esta aplicación revisa automáticamente cambios de código en GitLab usando OpenAI.</p>
    <p><a href="/health">Health Check</a></p>
    <p>Webhook endpoint: <code>POST /webhook</code></p>
    """, 200

@app.errorhandler(404)
def not_found(error):
    logger.warning(f"Endpoint no encontrado: {request.url}")
    return "Endpoint no encontrado", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error interno del servidor: {error}")
    return "Error interno del servidor", 500

if __name__ == '__main__':
    logger.info("=== INICIANDO APLICACIÓN ===")
    logger.info(f"Configuración de OpenAI:")
    logger.info(f"  - API Key configurada: {'Sí' if openai.api_key else 'No'}")
    logger.info(f"  - API Base: {getattr(openai, 'api_base', 'No configurado')}")
    logger.info(f"  - API Type: {getattr(openai, 'api_type', 'openai')}")
    logger.info(f"  - API Version: {getattr(openai, 'api_version', 'No configurado')}")
    logger.info(f"  - Modelo: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
    logger.info(f"Configuración de GitLab:")
    logger.info(f"  - URL: {gitlab_url}")
    logger.info(f"  - Token configurado: {'Sí' if gitlab_token else 'No'}")
    logger.info(f"  - Token esperado configurado: {'Sí' if os.environ.get('EXPECTED_GITLAB_TOKEN') else 'No'}")
    logger.info("Iniciando servidor Flask en puerto 8080...")
    
    try:
        app.run(host='0.0.0.0', port=8080, debug=False)
    except Exception as e:
        logger.error(f"Error al iniciar la aplicación: {e}")
        raise
