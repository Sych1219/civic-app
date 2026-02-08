"""
Simple verification script to test the backend setup.
"""

import os
import sys
from pathlib import Path


def check_environment():
    """Check if environment variables are set."""
    print("🔍 Checking environment variables...")
    
    required_vars = ["OPENAI_API_KEY", "API_BASE_URL"]
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if not value or value == f"your-{var.lower().replace('_', '-')}-here":
            missing_vars.append(var)
            print(f"  ❌ {var}: Not set or using default value")
        else:
            print(f"  ✅ {var}: Set")
    
    return len(missing_vars) == 0


def check_schema_file():
    """Check if schema file exists."""
    print("\n📄 Checking schema file...")
    
    schema_path = Path(__file__).parent / "design_docs" / "endpoint-schema-api-response.json"
    
    if schema_path.exists():
        print(f"  ✅ Schema file found: {schema_path}")
        return True
    else:
        print(f"  ❌ Schema file not found: {schema_path}")
        return False


def check_imports():
    """Check if all required modules can be imported."""
    print("\n📦 Checking Python modules...")
    
    required_modules = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("langchain_openai", "LangChain OpenAI"),
        ("pandas", "Pandas"),
        ("numpy", "NumPy"),
        ("sklearn", "scikit-learn"),
        ("httpx", "HTTPX"),
    ]
    
    all_ok = True
    
    for module, name in required_modules:
        try:
            __import__(module)
            print(f"  ✅ {name}: Installed")
        except ImportError:
            print(f"  ❌ {name}: Not installed")
            all_ok = False
    
    return all_ok


def check_app_files():
    """Check if all application files exist."""
    print("\n📂 Checking application files...")
    
    required_files = [
        "app/main.py",
        "app/models.py",
        "app/endpoint_matcher.py",
        "app/api_client.py",
        "app/data_processor.py",
        "app/utils.py",
    ]
    
    all_ok = True
    base_path = Path(__file__).parent
    
    for file_path in required_files:
        full_path = base_path / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}: Found")
        else:
            print(f"  ❌ {file_path}: Not found")
            all_ok = False
    
    return all_ok


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("🏙️  Civic App Backend - Setup Verification")
    print("=" * 60)
    
    # Load .env file if it exists
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv()
        print(f"\n✅ Loaded environment from {env_path}\n")
    else:
        print(f"\n⚠️  No .env file found. Please create one from .env.example\n")
    
    # Run checks
    env_ok = check_environment()
    schema_ok = check_schema_file()
    imports_ok = check_imports()
    files_ok = check_app_files()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Verification Summary")
    print("=" * 60)
    
    checks = [
        ("Environment Variables", env_ok),
        ("Schema File", schema_ok),
        ("Python Modules", imports_ok),
        ("Application Files", files_ok),
    ]
    
    all_passed = all(check[1] for check in checks)
    
    for name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    print("=" * 60)
    
    if all_passed:
        print("\n🎉 All checks passed! You're ready to start the server.")
        print("\nRun: ./start_server.sh")
        print("Or:  uvicorn app.main:app --reload")
        return 0
    else:
        print("\n⚠️  Some checks failed. Please fix the issues above.")
        print("\nFor setup instructions, see README.md")
        return 1


if __name__ == "__main__":
    sys.exit(main())
if __name__ == "__main__":
    print("="*50)
    print("  Civic App - Installation Verification")
    print("="*50 + "\n")
    
    deps_ok = check_imports()
    check_env_file()
    check_schema_file()
    
    print("\n" + "="*50)
    
    if not deps_ok:
        sys.exit(1)
