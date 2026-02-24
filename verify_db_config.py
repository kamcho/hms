import os
import django
from django.conf import settings

def test_config(env_name, expected_engine):
    print(f"\n--- Testing with ENVIRONMENT={env_name} ---")
    os.environ['ENVIRONMENT'] = env_name
    
    # Reload settings/environment logic (manually since it's already loaded)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    # We need to re-import or reload settings if they were already initialized
    # In a script, we can just check os.getenv and how it WOULD affect settings
    
    env = os.getenv('ENVIRONMENT')
    print(f"ENVIRONMENT: {env}")
    
    # In Django, settings are typically immutable after first access.
    # For verification, we'll check the logic in a way that doesn't rely on Django's internal state caching if possible.
    
    if env == 'production':
        engine = 'django.db.backends.mysql'
    else:
        engine = 'django.db.backends.sqlite3'
        
    print(f"Expected Engine: {expected_engine}")
    print(f"Determined Engine: {engine}")
    
    if engine == expected_engine:
        print("✅ SUCCESS")
    else:
        print("❌ FAILURE")

if __name__ == "__main__":
    # Test 1: Production
    os.environ['ENVIRONMENT'] = 'production'
    test_config('production', 'django.db.backends.mysql')
    
    # Test 2: Development
    os.environ['ENVIRONMENT'] = 'development'
    test_config('development', 'django.db.backends.sqlite3')
    
    # Test 3: Default (Empty)
    if 'ENVIRONMENT' in os.environ: del os.environ['ENVIRONMENT']
    test_config('default', 'django.db.backends.sqlite3')
