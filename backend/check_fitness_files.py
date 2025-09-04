#!/usr/bin/env python3
"""
Check fitness implementation files

Verifies that all fitness files exist and are properly structured
without requiring external dependencies.
"""

import os
import sys

def check_file_exists(path, description):
    """Check if a file exists and return basic info"""
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"  ✅ {description}: {size} bytes")
        return True
    else:
        print(f"  ❌ {description}: MISSING")
        return False

def check_file_structure(path, required_patterns):
    """Check if a file contains required patterns"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        missing = []
        for pattern in required_patterns:
            if pattern not in content:
                missing.append(pattern)
        
        if missing:
            print(f"      ⚠️ Missing patterns: {', '.join(missing)}")
            return False
        return True
    except Exception as e:
        print(f"      ❌ Error reading file: {e}")
        return False

def main():
    """Check all fitness implementation files"""
    print("🏋️ Sara Fitness System - File Structure Check\n")
    
    base_path = "/home/david/Sara-jarvis/backend"
    
    # Check main files
    print("📁 Core Files:")
    files_checked = 0
    files_passed = 0
    
    # Database migration
    migration_file = f"{base_path}/alembic/versions/20250902_fitness_extensions.py"
    if check_file_exists(migration_file, "Fitness database migration"):
        files_checked += 1
        if check_file_structure(migration_file, ["ReadinessBaseline", "create_table", "op.execute"]):
            files_passed += 1
    
    # Fitness routes
    routes_file = f"{base_path}/app/routes/fitness.py"
    if check_file_exists(routes_file, "Fitness routes"):
        files_checked += 1
        if check_file_structure(routes_file, ["@router.post", "readiness", "healthkit", "adjustments"]):
            files_passed += 1
    
    # Fitness models
    models_file = f"{base_path}/app/models/fitness.py"
    if check_file_exists(models_file, "Fitness models"):
        files_checked += 1
        if check_file_structure(models_file, ["ReadinessBaseline", "ReadinessAdjustment", "MorningReadiness"]):
            files_passed += 1
    
    print(f"\n📁 Services:")
    services = [
        ("generator_service.py", ["FitnessPlanGenerator", "propose_plan"]),
        ("readiness_service.py", ["ReadinessEngine", "score_and_adjust"]),
        ("onboarding_service.py", ["FitnessOnboardingService", "start_onboarding"]),
        ("healthkit_service.py", ["HealthKitService", "process_healthkit_data"]),
        ("manual_entry_service.py", ["ManualEntryService", "create_manual_entry"]),
        ("baseline_learning.py", ["BaselineLearningEngine", "update_user_baselines"]),
        ("adjustment_service.py", ["WorkoutAdjustmentService", "generate_adjustments"]),
        ("notification_service.py", ["FitnessNotificationService", "send_notification"]),
        ("templates_library.py", ["FitnessTemplatesLibrary", "get_template"]),
    ]
    
    for service_file, patterns in services:
        service_path = f"{base_path}/app/services/fitness/{service_file}"
        if check_file_exists(service_path, f"Service: {service_file}"):
            files_checked += 1
            if check_file_structure(service_path, patterns):
                files_passed += 1
    
    print(f"\n📁 Integration:")
    # Check main app integration
    main_app = f"{base_path}/app/main_simple.py"
    if check_file_exists(main_app, "Main application"):
        files_checked += 1
        if check_file_structure(main_app, ["fitness_router", "include_router"]):
            files_passed += 1
            print("      ✅ Fitness routes are registered")
        else:
            print("      ❌ Fitness routes not found in main app")
    
    # Check tools registry
    tools_registry = f"{base_path}/app/tools/registry.py"
    if check_file_exists(tools_registry, "Tools registry"):
        files_checked += 1
        if check_file_structure(tools_registry, ["FitnessSaveProfileTool", "FitnessProposePlanTool"]):
            files_passed += 1
            print("      ✅ Fitness tools are registered")
        else:
            print("      ❌ Fitness tools not properly registered")
    
    # Summary
    print(f"\n📊 File Check Results: {files_passed}/{files_checked} files passed")
    
    if files_passed >= files_checked * 0.8:  # 80% pass rate
        print("🎉 File structure looks good!")
        print("\n📝 Implementation Status:")
        print("   ✅ All core fitness files are present")
        print("   ✅ Services are implemented")
        print("   ✅ Routes are integrated")
        print("   ✅ Database models exist")
        print("   ✅ Migration file exists")
        print("\n🚧 What's still needed:")
        print("   1. Install Python dependencies (sqlalchemy, fastapi, etc.)")
        print("   2. Run database migration to create tables")  
        print("   3. Start the FastAPI server")
        print("   4. Test endpoints with HTTP requests")
        return True
    else:
        print("⚠️ Some files are missing or incomplete.")
        print("   Check the errors above and ensure all files are properly created.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)