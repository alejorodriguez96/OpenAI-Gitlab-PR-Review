#!/usr/bin/env python3
"""
Script de prueba para simular webhooks de GitLab
Útil para debugging sin necesidad de configurar webhooks reales
"""

import requests
import json
import os
from datetime import datetime

# Configuración
WEBHOOK_URL = "http://localhost:8080/webhook"
EXPECTED_TOKEN = "test-token-123"  # Debe coincidir con EXPECTED_GITLAB_TOKEN

def test_health_check():
    """Prueba el endpoint de health check"""
    print("=== PROBANDO HEALTH CHECK ===")
    try:
        response = requests.get("http://localhost:8080/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_merge_request_webhook():
    """Simula un webhook de merge request"""
    print("\n=== PROBANDO WEBHOOK DE MERGE REQUEST ===")
    
    payload = {
        "object_kind": "merge_request",
        "object_attributes": {
            "action": "open",
            "iid": 123,
            "title": "Test MR",
            "description": "MR de prueba"
        },
        "project": {
            "id": 1,
            "name": "test-project"
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Token": EXPECTED_TOKEN
    }
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_push_webhook():
    """Simula un webhook de push"""
    print("\n=== PROBANDO WEBHOOK DE PUSH ===")
    
    payload = {
        "object_kind": "push",
        "project_id": 1,
        "after": "abc123def456",
        "project": {
            "name": "test-project"
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Token": EXPECTED_TOKEN
    }
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_invalid_token():
    """Prueba con token inválido"""
    print("\n=== PROBANDO TOKEN INVÁLIDO ===")
    
    payload = {"object_kind": "merge_request"}
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Token": "invalid-token"
    }
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 403
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    print(f"Probando aplicación en {datetime.now()}")
    print(f"URL del webhook: {WEBHOOK_URL}")
    print(f"Token esperado: {EXPECTED_TOKEN}")
    
    # Verificar que la aplicación esté corriendo
    if not test_health_check():
        print("\n❌ La aplicación no está corriendo o no está configurada correctamente")
        print("Asegúrate de que:")
        print("1. La aplicación esté ejecutándose (python main.py)")
        print("2. Las variables de entorno estén configuradas")
        print("3. EXPECTED_GITLAB_TOKEN sea igual a 'test-token-123'")
        return
    
    print("\n✅ Health check exitoso")
    
    # Ejecutar pruebas
    tests = [
        ("Health Check", test_health_check),
        ("Token Inválido", test_invalid_token),
        ("Merge Request", test_merge_request_webhook),
        ("Push Event", test_push_webhook)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            status = "✅" if result else "❌"
            print(f"{status} {test_name}")
        except Exception as e:
            print(f"❌ {test_name} - Error: {e}")
            results.append((test_name, False))
    
    # Resumen
    print(f"\n=== RESUMEN ===")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    print(f"Pruebas pasadas: {passed}/{total}")
    
    if passed == total:
        print("🎉 Todas las pruebas pasaron!")
    else:
        print("⚠️  Algunas pruebas fallaron. Revisa los logs para más detalles.")

if __name__ == "__main__":
    main()
