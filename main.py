import os
import json
import requests
import logging
from flask import Flask, request, render_template_string
from openai import OpenAI

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
gitlab_token = os.environ.get("GITLAB_TOKEN")
gitlab_url = os.environ.get("GITLAB_URL")

# Inicializar cliente de OpenAI para Responses API
def get_openai_client():
    """Inicializa y retorna el cliente de OpenAI configurado para Responses API"""
    api_key = os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("AZURE_OPENAI_API_BASE")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
    
    if api_base is not None:
        logger.info(f"Usando Azure OpenAI con base URL: {api_base}")
        return OpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"api-version": api_version} if api_version else None
        )
    else:
        return OpenAI(api_key=api_key)

# Cliente global de OpenAI (se inicializa cuando se necesita)
openai_client = get_openai_client()

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

        # Preparar el input para la API de Responses
        input_text = f"{pre_prompt}\n\n{''.join(diffs)}{questions}"
        
        logger.info("Enviando solicitud a OpenAI usando Responses API...")
        logger.info(f"Modelo a usar: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
        
        try:            
            # Usar la API de Responses
            response = openai_client.responses.create(
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                input=input_text,
                instructions="Eres un desarrollador senior especializado en arquitectura de software, revisando cambios de código con enfoque en arquitectura hexagonal, separación de responsabilidades, orientación a objetos y mejores prácticas de desarrollo. Responde en markdown compatible con GitLab. Incluye una versión concisa de cada pregunta en tu respuesta, prestando especial atención a los aspectos arquitectónicos y de diseño."
            )
            logger.info("Respuesta de OpenAI recibida exitosamente")
            answer = response.output_text.strip()
            answer += "\n\nEste comentario fue generado por inteligencia artificial."
        except Exception as e:
            logger.error(f"Error al llamar a OpenAI: {e}")
            answer = "Lo siento, no me siento bien hoy. Por favor, pide a un humano que revise este PR."
            answer += "\n\nEste comentario fue generado por inteligencia artificial."
            answer += f"\n\nError: {str(e)}"
        try:
            logger.info(f"Metricas: {response.usage}")
        except Exception as e:
            logger.error(f"Error al obtener metricas: {e}")
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


def extract_mr_iid_from_url(mr_url):
    """Extrae el IID del MR desde una URL de GitLab."""
    try:
        # Ejemplos válidos:
        # https://gitlab.com/grupo/proyecto/-/merge_requests/123
        # https://gitlab.com/grupo/proyecto/merge_requests/123
        parts = mr_url.rstrip("/").split("/")
        iid_str = parts[-1]
        if not iid_str.isdigit():
            return None
        return int(iid_str)
    except Exception as e:
        logger.error(f"No se pudo extraer el IID del MR desde la URL '{mr_url}': {e}")
        return None


def build_ai_review_for_mr(project_id, mr_iid):
    """Genera el texto de la review de MR usando OpenAI."""
    changes_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_iid}/changes"
    logger.info(f"URL de cambios para review manual: {changes_url}")

    headers = {"Private-Token": gitlab_token}
    logger.info("Obteniendo cambios del MR desde GitLab (review manual)...")

    response = requests.get(changes_url, headers=headers)
    logger.info(f"Respuesta de GitLab - Status: {response.status_code}")

    if response.status_code != 200:
        logger.error(f"Error al obtener cambios del MR: {response.status_code} - {response.text}")
        raise RuntimeError(f"Error al obtener cambios del MR: {response.status_code}")

    mr_changes = response.json()
    logger.info(f"Cambios obtenidos: {len(mr_changes.get('changes', []))} archivos modificados")

    diffs = [change["diff"] for change in mr_changes.get("changes", [])]
    logger.info(f"Total de diffs: {len(diffs)}")

    pre_prompt = (
        "Revisa los siguientes cambios de código git diff, enfocándote en estructura, seguridad, claridad, "
        "arquitectura hexagonal, separación de responsabilidades y orientación a objetos."
    )

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

    input_text = f"{pre_prompt}\n\n{''.join(diffs)}{questions}"

    logger.info("Enviando solicitud a OpenAI usando Responses API (review manual)...")
    logger.info(f"Modelo a usar: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")

    try:
        response = openai_client.responses.create(
            model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
            input=input_text,
            instructions=(
                "Eres un desarrollador senior especializado en arquitectura de software, revisando cambios de "
                "código con enfoque en arquitectura hexagonal, separación de responsabilidades, orientación a "
                "objetos y mejores prácticas de desarrollo. Responde en markdown compatible con GitLab. "
                "Incluye una versión concisa de cada pregunta en tu respuesta, prestando especial atención a los "
                "aspectos arquitectónicos y de diseño."
            ),
        )
        logger.info("Respuesta de OpenAI recibida exitosamente (review manual)")
        answer = response.output_text.strip()
        answer += "\n\nEste comentario fue generado por inteligencia artificial."
    except Exception as e:
        logger.error(f"Error al llamar a OpenAI (review manual): {e}")
        answer = (
            "Lo siento, no me siento bien hoy. Por favor, pide a un humano que revise este MR.\n\n"
            "Este comentario fue generado por inteligencia artificial.\n\n"
            f"Error: {str(e)}"
        )

    try:
        logger.info(f"Métricas de OpenAI (review manual): {response.usage}")
    except Exception as e:
        logger.error(f"Error al obtener métricas (review manual): {e}")

    logger.info(f"Respuesta generada (review manual, longitud: {len(answer)} caracteres)")
    logger.info(f"Respuesta (primeros 200 chars): {answer[:200]}...")

    return answer


def create_pending_review_draft_note(project_id, mr_iid, body):
    """Crea un draft note en el MR, dejando la review en estado pendiente."""
    draft_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_iid}/draft_notes"
    headers = {"Private-Token": gitlab_token}
    payload = {"note": body}

    logger.info(f"Creando draft note (review pendiente) en: {draft_url}")
    response = requests.post(draft_url, headers=headers, json=payload)
    logger.info(f"Respuesta de GitLab al crear draft note - Status: {response.status_code}")

    if response.status_code != 201:
        logger.error(f"Error al crear draft note: {response.text}")
        raise RuntimeError(f"Error al crear draft note: {response.status_code}")

    logger.info("Draft note creado exitosamente; la review queda en estado pendiente.")


def build_annotated_diffs_for_ai(mr_changes):
    """
    Construye un string con diffs anotados con números de línea reales (lado nuevo)
    para que OpenAI pueda referenciar archivos y líneas concretas.
    """
    annotated_parts = []

    for change in mr_changes.get("changes", []):
        new_path = change.get("new_path") or change.get("old_path")
        diff_text = change.get("diff", "")

        if not diff_text:
            continue

        annotated_parts.append(f"=== FILE: {new_path} ===")

        lines = diff_text.splitlines()
        new_line = None

        for line in lines:
            # Cabecera de hunk: @@ -a,b +c,d @@
            if line.startswith("@@"):
                try:
                    header = line.split("@@")[1].strip()
                    # header ej: "-10,7 +10,9"
                    plus_part = [p for p in header.split(" ") if p.startswith("+")][0]
                    plus_numbers = plus_part[1:]  # sin el '+'
                    if "," in plus_numbers:
                        start_new = int(plus_numbers.split(",")[0])
                    else:
                        start_new = int(plus_numbers)
                    new_line = start_new
                except Exception as e:
                    logger.error(f"No se pudo parsear cabecera de hunk '{line}': {e}")
                    new_line = None

                annotated_parts.append(line)
                continue

            if new_line is None:
                annotated_parts.append(line)
                continue

            prefix = line[:1]
            content = line[1:]

            if prefix == "+":
                # Línea nueva: tiene número de línea nuevo
                annotated_parts.append(f"[{new_line}] +{content}")
                new_line += 1
            elif prefix == " ":
                # Contexto: también tiene línea nueva
                annotated_parts.append(f"[{new_line}]  {content}")
                new_line += 1
            elif prefix == "-":
                # Línea borrada: no incrementa new_line
                annotated_parts.append(f"      -{content}")
            else:
                annotated_parts.append(line)

        annotated_parts.append("")  # separador entre archivos

    return "\n".join(annotated_parts)


def generate_inline_draft_notes_for_mr(project_id, mr_iid):
    """
    Usa OpenAI para sugerir comentarios inline y los crea como draft notes
    en el MR correspondiente (quedan en pending).
    """
    try:
        # 1) Obtener información del MR (incluye diff_refs)
        mr_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_iid}"
        headers = {"Private-Token": gitlab_token}

        logger.info(f"Obteniendo información del MR para inline comments: {mr_url}")
        mr_resp = requests.get(mr_url, headers=headers)
        logger.info(f"Respuesta MR info - Status: {mr_resp.status_code}")

        if mr_resp.status_code != 200:
            logger.error(f"No se pudo obtener info del MR: {mr_resp.status_code} - {mr_resp.text}")
            return

        mr_data = mr_resp.json()
        diff_refs = mr_data.get("diff_refs") or {}
        base_sha = diff_refs.get("base_sha")
        start_sha = diff_refs.get("start_sha")
        head_sha = diff_refs.get("head_sha")

        if not (base_sha and start_sha and head_sha):
            logger.error("diff_refs incompletos; no se pueden crear inline comments.")
            return

        # 2) Obtener cambios del MR
        changes_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_iid}/changes"
        logger.info(f"Obteniendo cambios del MR para inline comments: {changes_url}")
        changes_resp = requests.get(changes_url, headers=headers)
        logger.info(f"Respuesta MR changes (inline) - Status: {changes_resp.status_code}")

        if changes_resp.status_code != 200:
            logger.error(f"No se pudieron obtener cambios del MR: {changes_resp.status_code} - {changes_resp.text}")
            return

        mr_changes = changes_resp.json()
        annotated_diffs = build_annotated_diffs_for_ai(mr_changes)

        if not annotated_diffs.strip():
            logger.info("No hay diffs anotados para enviar a OpenAI (inline comments).")
            return

        # 3) Llamar a OpenAI para obtener sugerencias de comentarios inline
        inline_prompt = """
Eres un revisor de código senior. A continuación verás diffs de GitLab
con números de línea reales anotados entre corchetes, por ejemplo:

=== FILE: src/app.py ===
@@ -10,7 +10,9 @@
[42] +def nueva_funcion():

Genera comentarios SOLO en las partes donde realmente haya algo importante
que revisar (bugs potenciales, problemas serios de diseño, seguridad, etc.).

Responde ÚNICAMENTE con un JSON válido de la forma:
{
  "comments": [
    {
      "file_path": "ruta/archivo.py",
      "new_line": 42,
      "text": "Comentario conciso en español para esa línea."
    }
  ]
}

Reglas:
- Usa exactamente las rutas de archivo que aparecen después de "=== FILE: ... ===".
- Usa exactamente los números de línea que aparecen entre corchetes [].
- No repitas el comentario general del MR.
- Si no tienes nada importante que comentar inline, responde {"comments": []}.
"""

        input_text = f"{inline_prompt}\n\n{annotated_diffs}"

        logger.info("Enviando solicitud a OpenAI para generar comentarios inline...")
        response = openai_client.responses.create(
            model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
            input=input_text,
            instructions="Devuelve SOLO JSON válido, sin texto adicional.",
        )
        raw_output = response.output_text.strip()
        logger.info(f"Respuesta de OpenAI (inline) recibida, longitud: {len(raw_output)}")

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.error(f"No se pudo parsear la respuesta de OpenAI como JSON para inline comments: {e}")
            logger.error(f"Respuesta cruda: {raw_output[:500]}...")
            return

        comments = parsed.get("comments") or []
        if not comments:
            logger.info("OpenAI no sugirió comentarios inline adicionales.")
            return

        logger.info(f"Se recibieron {len(comments)} comentarios inline sugeridos por OpenAI.")

        # 4) Crear draft notes inline en GitLab
        draft_url = f"{gitlab_url}/projects/{project_id}/merge_requests/{mr_iid}/draft_notes"

        for idx, c in enumerate(comments):
            try:
                file_path = c.get("file_path")
                new_line = c.get("new_line")
                text = c.get("text", "").strip()

                if not (file_path and isinstance(new_line, int) and text):
                    logger.warning(f"Comentario inline #{idx} inválido o incompleto: {c}")
                    continue

                payload = {
                    "note": text,
                    "position": {
                        "position_type": "text",
                        "base_sha": base_sha,
                        "start_sha": start_sha,
                        "head_sha": head_sha,
                        "new_path": file_path,
                        "new_line": new_line,
                    },
                }

                logger.info(f"Creando draft note inline para {file_path}:{new_line}")
                draft_resp = requests.post(draft_url, headers=headers, json=payload)
                logger.info(f"Respuesta draft note inline - Status: {draft_resp.status_code}")

                if draft_resp.status_code != 201:
                    logger.error(f"Error al crear draft note inline: {draft_resp.text}")
            except Exception as e:
                logger.error(f"Error al procesar comentario inline #{idx}: {e}")

    except Exception as e:
        logger.error(f"Error inesperado generando comentarios inline para MR {mr_iid}: {e}")
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

        # Preparar el input para la API de Responses
        input_text = f"{pre_prompt}\n\n{changes_string}{questions}"
        
        logger.info("Enviando solicitud a OpenAI para revisión de commit usando Responses API...")
        logger.info(f"Modelo a usar: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
        
        try:
            # Inicializar cliente si no está inicializado
            global openai_client
            if openai_client is None:
                openai_client = get_openai_client()
            
            # Usar la API de Responses
            response = openai_client.responses.create(
                model=os.environ.get("OPENAI_API_MODEL") or "gpt-3.5-turbo",
                input=input_text,
                instructions="Eres un desarrollador senior especializado en arquitectura de software, revisando cambios de código de un commit con enfoque en arquitectura hexagonal, separación de responsabilidades, orientación a objetos y mejores prácticas de desarrollo. Responde en markdown para GitLab. Incluye versiones concisas de las preguntas en la respuesta, prestando especial atención a los aspectos arquitectónicos y de diseño."
            )
            logger.info("Respuesta de OpenAI recibida exitosamente")
            answer = response.output[0].content[0].text.strip()
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
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "gitlab_configured": bool(gitlab_token and gitlab_url),
        "expected_token_configured": bool(os.environ.get("EXPECTED_GITLAB_TOKEN")),
        "azure_configured": bool(os.environ.get("AZURE_OPENAI_API_BASE")),
        "api_type": "responses"
    }
    
    all_configured = all(status.values())
    if not all_configured:
        status["status"] = "unhealthy"
        logger.warning("Health check fallido - configuración incompleta")
    
    return json.dumps(status, indent=2), 200 if all_configured else 500

@app.route('/', methods=['GET'])
def root():
    """Endpoint raíz con información básica y acceso al formulario de review manual."""
    logger.info("Solicitud al endpoint raíz")
    html = """
    <html>
      <head>
        <title>Revisor de Código con IA</title>
        <style>
          body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; background: #f5f5f7; color: #111827; }
          .card { max-width: 640px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 1.75rem 2rem; box-shadow: 0 18px 45px rgba(15,23,42,0.12); border: 1px solid #e5e7eb; }
          h1 { font-size: 1.8rem; margin-bottom: 0.25rem; }
          p { margin: 0.25rem 0 0.75rem 0; line-height: 1.6; }
          .muted { color: #6b7280; font-size: 0.95rem; }
          .links { margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.5rem; }
          a { color: #2563eb; text-decoration: none; font-weight: 500; }
          a:hover { text-decoration: underline; }
          .pill { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; padding: 0.15rem 0.55rem; border-radius: 999px; background: #eff6ff; color: #1d4ed8; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
        </style>
      </head>
      <body>
        <div class="card">
          <div class="pill">GitLab · OpenAI</div>
          <h1>Revisor de Código con IA</h1>
          <p class="muted">
            Esta aplicación revisa automáticamente cambios de código en GitLab usando OpenAI, tanto por webhooks
            como manualmente a partir de un enlace a Merge Request.
          </p>
          <div class="links">
            <a href="/review">➜ Abrir formulario de review manual</a>
            <a href="/health">➜ Health Check</a>
            <span class="muted">Webhook endpoint: <code>POST /webhook</code></span>
          </div>
        </div>
      </body>
    </html>
    """
    return html, 200


REVIEW_FORM_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <title>Review manual de Merge Request</title>
    <style>
      * { box-sizing: border-box; }
      body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; background: #f5f5f7; color: #111827; }
      .page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
      .card { width: 100%; max-width: 720px; background: #ffffff; border-radius: 16px; padding: 2rem 2.25rem 2.25rem; box-shadow: 0 22px 55px rgba(15,23,42,0.13); border: 1px solid #e5e7eb; }
      h1 { font-size: 1.7rem; margin: 0 0 0.25rem 0; }
      .subtitle { margin: 0 0 1.5rem 0; color: #6b7280; font-size: 0.95rem; }
      form { display: flex; flex-direction: column; gap: 1.1rem; margin-top: 0.5rem; }
      label { font-weight: 500; font-size: 0.92rem; color: #374151; display: block; margin-bottom: 0.25rem; }
      input[type="text"], input[type="password"] {
        width: 100%;
        padding: 0.6rem 0.75rem;
        border-radius: 0.6rem;
        border: 1px solid #d1d5db;
        font-size: 0.95rem;
        outline: none;
        background: #f9fafb;
        transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
      }
      input[type="text"]:focus, input[type="password"]:focus {
        border-color: #2563eb;
        box-shadow: 0 0 0 1px rgba(37,99,235,0.18);
        background: #ffffff;
      }
      .hint { font-size: 0.8rem; color: #9ca3af; margin-top: 0.15rem; }
      .actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.25rem; align-items: center; flex-wrap: wrap; }
      .btn-primary {
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: #ffffff;
        border: none;
        border-radius: 999px;
        padding: 0.55rem 1.3rem;
        font-size: 0.93rem;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        box-shadow: 0 14px 30px rgba(37,99,235,0.35);
        transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
      }
      .btn-primary:hover {
        transform: translateY(-1px);
        box-shadow: 0 16px 36px rgba(37,99,235,0.45);
      }
      .btn-primary:active {
        transform: translateY(0);
        box-shadow: 0 10px 24px rgba(37,99,235,0.3);
      }
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.18rem 0.65rem;
        border-radius: 999px;
        background: #ecfdf5;
        color: #047857;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.78rem;
        padding: 0.18rem 0.6rem;
        border-radius: 999px;
        background: #eff6ff;
        color: #1d4ed8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .top-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem; gap: 1rem; flex-wrap: wrap; }
      .status {
        padding: 0.5rem 0.75rem;
        border-radius: 0.65rem;
        font-size: 0.85rem;
        margin-top: 0.75rem;
      }
      .status-ok { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
      .status-error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
      .status-neutral { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
      .status-title { font-weight: 600; display: block; margin-bottom: 0.15rem; }
      .status-body { font-size: 0.86rem; }
      .footer-links { margin-top: 1.5rem; font-size: 0.82rem; display: flex; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; color: #9ca3af; }
      .footer-links a { color: #6b7280; text-decoration: none; font-weight: 500; }
      .footer-links a:hover { text-decoration: underline; }
      code { background: #f3f4f6; padding: 0.1rem 0.3rem; border-radius: 999px; font-size: 0.8rem; }
    </style>
  </head>
  <body>
    <div class="page">
      <div class="card">
        <div class="top-row">
          <div>
            <h1>Review manual de Merge Request</h1>
            <p class="subtitle">
              Genera una review con IA a partir de un enlace de MR de GitLab. La review quedará
              <strong>en estado pendiente</strong> como draft note, para que puedas revisarla y publicarla cuando quieras.
            </p>
          </div>
          <div class="pill">GitLab · Pending Review</div>
        </div>

        {% if status %}
          <div class="status {% if status_type == 'ok' %}status-ok{% elif status_type == 'error' %}status-error{% else %}status-neutral{% endif %}">
            <span class="status-title">{{ status_title }}</span>
            <span class="status-body">{{ status }}</span>
          </div>
        {% endif %}

        <form method="post" action="/review">
          <div>
            <label for="expected_token">Token esperado (seguridad)</label>
            <input
              id="expected_token"
              name="expected_token"
              type="password"
              autocomplete="off"
              required
              placeholder="Introduce el EXPECTED_GITLAB_TOKEN configurado en el servidor"
            />
            <p class="hint">
              Solo se compara del lado del servidor con <code>EXPECTED_GITLAB_TOKEN</code>. No se persiste ni se reenvía a otros servicios.
            </p>
          </div>

          <div>
            <label for="mr_url">Enlace al Merge Request</label>
            <input
              id="mr_url"
              name="mr_url"
              type="text"
              required
              placeholder="Ej: https://gitlab.com/grupo/proyecto/-/merge_requests/123"
            />
            <p class="hint">
              Usaremos este enlace para obtener el IID del MR e invocar la API de GitLab.
            </p>
          </div>

          <div class="actions">
            <span class="badge">La review se creará como draft note pendiente</span>
            <button class="btn-primary" type="submit">
              Generar review con IA
            </button>
          </div>
        </form>

        <div class="footer-links">
          <span>Webhook: <code>POST /webhook</code></span>
          <a href="/">Volver al inicio</a>
        </div>
      </div>
    </div>
  </body>
  </html>
"""


@app.route("/review", methods=["GET", "POST"])
def manual_review():
    """Formulario sencillo de UI para generar una review pendiente a partir de un enlace de MR."""
    logger.info(f"Solicitud al endpoint /review con método {request.method}")

    if request.method == "GET":
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status=None,
            status_type=None,
            status_title="",
        ), 200

    # POST: procesar el formulario
    expected_token_input = request.form.get("expected_token", "")
    mr_url = request.form.get("mr_url", "").strip()

    configured_expected_token = os.environ.get("EXPECTED_GITLAB_TOKEN")

    if not configured_expected_token:
        logger.error("EXPECTED_GITLAB_TOKEN no está configurado en el entorno")
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status="El servidor no tiene configurado EXPECTED_GITLAB_TOKEN. Revisa la configuración.",
            status_type="error",
            status_title="Configuración incompleta",
        ), 500

    if expected_token_input != configured_expected_token:
        logger.warning("Token esperado recibido desde la UI no coincide con EXPECTED_GITLAB_TOKEN")
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status="El token proporcionado no coincide con el token esperado. Acceso denegado.",
            status_type="error",
            status_title="Token inválido",
        ), 403

    if not mr_url:
        logger.warning("No se proporcionó URL de MR en el formulario")
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status="Debes proporcionar un enlace válido al Merge Request.",
            status_type="error",
            status_title="Enlace faltante",
        ), 400

    mr_iid = extract_mr_iid_from_url(mr_url)
    if mr_iid is None:
        logger.warning(f"No se pudo extraer el IID del MR desde la URL proporcionada: {mr_url}")
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status="No se pudo detectar el número de MR a partir del enlace. Verifica que el enlace sea correcto.",
            status_type="error",
            status_title="Enlace de MR no válido",
        ), 400

    try:
        # Buscar el MR globalmente por IID para obtener el project_id
        search_url = f"{gitlab_url}/merge_requests"
        headers = {"Private-Token": gitlab_token}
        params = {"iid": mr_iid}

        logger.info(f"Buscando MR por IID usando la API de GitLab: {search_url} con iid={mr_iid}")
        search_response = requests.get(search_url, headers=headers, params=params)
        logger.info(f"Respuesta de búsqueda de MR - Status: {search_response.status_code}")

        if search_response.status_code != 200:
            logger.error(f"Error al buscar MR por IID: {search_response.status_code} - {search_response.text}")
            return render_template_string(
                REVIEW_FORM_TEMPLATE,
                status="No se pudo encontrar el Merge Request en GitLab. Revisa que el MR exista y que el token tenga permisos.",
                status_type="error",
                status_title="Error buscando el MR",
            ), 500

        mrs = search_response.json()
        if not mrs:
            logger.warning(f"No se encontró ningún MR con IID {mr_iid}")
            return render_template_string(
                REVIEW_FORM_TEMPLATE,
                status="No se encontró ningún Merge Request con ese número de IID. Verifica el enlace.",
                status_type="error",
                status_title="MR no encontrado",
            ), 404

        mr_data = mrs[0]
        project_id = mr_data.get("project_id")
        logger.info(f"MR encontrado: IID {mr_iid}, project_id {project_id}")

        if not project_id:
            logger.error("La respuesta de GitLab no incluye project_id para el MR encontrado")
            return render_template_string(
                REVIEW_FORM_TEMPLATE,
                status="No se pudo determinar el proyecto del Merge Request. Revisa los logs del servidor.",
                status_type="error",
                status_title="Datos incompletos del MR",
            ), 500

        review_body = build_ai_review_for_mr(project_id, mr_iid)
        create_pending_review_draft_note(project_id, mr_iid, review_body)
        # Comentarios inline (quedan también como draft notes, en pending)
        generate_inline_draft_notes_for_mr(project_id, mr_iid)

        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status=(
                f"Se generó correctamente una review pendiente para el MR !{mr_iid}, "
                "incluyendo un comentario general y comentarios inline en el código donde corresponde. "
                "Puedes revisarlos y publicarlos desde GitLab."
            ),
            status_type="ok",
            status_title="Review pendiente creada",
        ), 200

    except Exception as e:
        logger.error(f"Error inesperado generando review manual para MR {mr_iid}: {e}")
        return render_template_string(
            REVIEW_FORM_TEMPLATE,
            status=f"Ocurrió un error al generar la review: {str(e)}",
            status_type="error",
            status_title="Error interno",
        ), 500

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
    logger.info(f"  - API Key configurada: {'Sí' if os.environ.get('OPENAI_API_KEY') else 'No'}")
    logger.info(f"  - API Base: {os.environ.get('AZURE_OPENAI_API_BASE', 'No configurado')}")
    logger.info(f"  - API Version: {os.environ.get('AZURE_OPENAI_API_VERSION', 'No configurado')}")
    logger.info(f"  - Modelo: {os.environ.get('OPENAI_API_MODEL', 'gpt-3.5-turbo')}")
    logger.info(f"  - API Type: Responses API")
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
