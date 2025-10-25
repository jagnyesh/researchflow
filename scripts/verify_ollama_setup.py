#!/usr/bin/env python3
"""
Ollama Setup Verification Script

Verifies that Ollama is properly installed, running, and configured
for use with ResearchFlow's multi-provider LLM setup.
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Color codes for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_header(text):
    """Print a section header"""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}{text.center(70)}{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")


def print_success(text):
    """Print success message"""
    print(f"{GREEN}✓ {text}{RESET}")


def print_warning(text):
    """Print warning message"""
    print(f"{YELLOW}⚠ {text}{RESET}")


def print_error(text):
    """Print error message"""
    print(f"{RED}✗ {text}{RESET}")


def check_ollama_binary():
    """Check if Ollama binary is installed"""
    print_header("STEP 1: Ollama Binary Check")

    result = os.popen("which ollama").read().strip()
    if result:
        print_success(f"Ollama found at: {result}")

        # Check version
        version = os.popen("ollama --version").read().strip()
        print_success(f"Version: {version}")
        return True
    else:
        print_error("Ollama not found in PATH")
        print(f"\n{YELLOW}Installation instructions:{RESET}")
        print("  macOS:   brew install ollama")
        print("  Linux:   curl https://ollama.ai/install.sh | sh")
        print("  Windows: Download from https://ollama.ai\n")
        return False


def check_ollama_service():
    """Check if Ollama service is running"""
    print_header("STEP 2: Ollama Service Check")

    result = os.popen("ps aux | grep -i '[o]llama serve'").read().strip()
    if result:
        print_success("Ollama service is running")
        print(f"  {result[:100]}...")
        return True
    else:
        print_error("Ollama service is not running")
        print(f"\n{YELLOW}To start Ollama:{RESET}")
        print("  Terminal: ollama serve")
        print("  Or launch the Ollama app\n")
        return False


def check_ollama_api():
    """Check if Ollama API is accessible"""
    print_header("STEP 3: Ollama API Check")

    load_dotenv()
    base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code == 200:
            print_success(f"Ollama API responding at {base_url}")

            data = response.json()
            models = data.get('models', [])
            print_success(f"Found {len(models)} installed model(s)")

            for model in models:
                name = model.get('name', 'unknown')
                size_bytes = model.get('size', 0)
                size_gb = size_bytes / (1024 ** 3)
                print(f"  • {name} ({size_gb:.2f} GB)")

            return True, models
        else:
            print_error(f"API returned status code {response.status_code}")
            return False, []
    except requests.exceptions.RequestException as e:
        print_error(f"Cannot connect to Ollama API: {str(e)}")
        print(f"\n{YELLOW}Troubleshooting:{RESET}")
        print("  1. Ensure Ollama is running: ollama serve")
        print("  2. Check OLLAMA_BASE_URL in .env matches your setup")
        print(f"  3. Try: curl {base_url}/api/tags\n")
        return False, []


def check_env_configuration():
    """Check .env file configuration"""
    print_header("STEP 4: Environment Configuration Check")

    load_dotenv()

    # Check ANTHROPIC_API_KEY
    anthropic_key = os.getenv('ANTHROPIC_API_KEY')
    if anthropic_key and anthropic_key.startswith('sk-ant-'):
        print_success(f"ANTHROPIC_API_KEY: {anthropic_key[:20]}...")
    else:
        print_warning("ANTHROPIC_API_KEY not set or invalid")

    # Check SECONDARY_LLM_PROVIDER
    provider = os.getenv('SECONDARY_LLM_PROVIDER', 'anthropic')
    print_success(f"SECONDARY_LLM_PROVIDER: {provider}")

    # Check provider-specific config
    if provider == 'ollama':
        ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
        print_success(f"OLLAMA_BASE_URL: {ollama_url}")

        model = os.getenv('SECONDARY_LLM_MODEL', 'not set')
        if model and model != 'not set':
            print_success(f"SECONDARY_LLM_MODEL: {model}")
        else:
            print_warning("SECONDARY_LLM_MODEL not set (will use default)")

    elif provider == 'openai':
        openai_key = os.getenv('OPENAI_API_KEY')
        if openai_key and openai_key.startswith('sk-'):
            print_success(f"OPENAI_API_KEY: {openai_key[:20]}...")
        else:
            print_error("OPENAI_API_KEY not set but SECONDARY_LLM_PROVIDER=openai")

    # Check fallback setting
    fallback = os.getenv('ENABLE_LLM_FALLBACK', 'true')
    print_success(f"ENABLE_LLM_FALLBACK: {fallback}")

    return True


def check_recommended_models(installed_models):
    """Check if recommended models are installed"""
    print_header("STEP 5: Recommended Models Check")

    recommended = {
        'llama3.2:3b': '2GB - Fastest, good for testing',
        'llama3:8b': '4.7GB - Best balance (recommended)',
        'phi3.5': '2.2GB - Microsoft, very fast',
    }

    installed_names = [m.get('name', '') for m in installed_models]

    print("Checking for recommended models:\n")

    missing_models = []
    for model_name, description in recommended.items():
        if model_name in installed_names:
            print_success(f"{model_name} - {description}")
        else:
            print_warning(f"{model_name} - NOT INSTALLED - {description}")
            missing_models.append(model_name)

    if missing_models:
        print(f"\n{YELLOW}To download missing models:{RESET}")
        for model in missing_models:
            print(f"  ollama pull {model}")

    return len(missing_models) == 0


def test_ollama_inference():
    """Test a simple inference with Ollama"""
    print_header("STEP 6: Ollama Inference Test")

    load_dotenv()
    base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    model = os.getenv('SECONDARY_LLM_MODEL', 'llama3:8b')

    try:
        print(f"Testing inference with model: {model}")
        print(f"Prompt: 'Say hello in one sentence'")

        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": "Say hello in one sentence",
                "stream": False
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            generated_text = data.get('response', '').strip()

            if generated_text:
                print_success("Inference successful!")
                print(f"\n{BLUE}Response:{RESET}")
                print(f"  {generated_text}\n")
                return True
            else:
                print_error("Inference returned empty response")
                return False
        else:
            print_error(f"Inference failed with status {response.status_code}")
            print(f"  {response.text}")
            return False

    except requests.exceptions.Timeout:
        print_error("Inference timed out (>30s)")
        print(f"\n{YELLOW}Possible causes:{RESET}")
        print(f"  • Model '{model}' not downloaded")
        print(f"  • Model too large for your hardware")
        print(f"  • Try a smaller model like llama3.2:3b")
        return False

    except Exception as e:
        print_error(f"Inference failed: {str(e)}")
        return False


def main():
    """Main verification flow"""
    print(f"\n{BLUE}{'=' * 70}")
    print(f"  ResearchFlow - Ollama Setup Verification")
    print(f"{'=' * 70}{RESET}\n")

    results = {}

    # Run all checks
    results['binary'] = check_ollama_binary()
    results['service'] = check_ollama_service()
    api_ok, models = check_ollama_api()
    results['api'] = api_ok
    results['config'] = check_env_configuration()
    results['models'] = check_recommended_models(models) if api_ok else False
    results['inference'] = test_ollama_inference() if api_ok and models else False

    # Summary
    print_header("VERIFICATION SUMMARY")

    all_passed = all(results.values())

    for check, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        color = GREEN if passed else RED
        print(f"{color}{status:<10}{RESET} {check.replace('_', ' ').title()}")

    print()

    if all_passed:
        print(f"{GREEN}{'=' * 70}")
        print(f"  ✓ ALL CHECKS PASSED - Ollama is ready to use!")
        print(f"{'=' * 70}{RESET}\n")
        print(f"{BLUE}Next steps:{RESET}")
        print("  1. Run: python scripts/test_multi_provider.py")
        print("  2. Or test in Streamlit: streamlit run app/web_ui/researcher_portal.py\n")
        return 0
    else:
        print(f"{RED}{'=' * 70}")
        print(f"  ✗ SOME CHECKS FAILED - Please fix the issues above")
        print(f"{'=' * 70}{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
