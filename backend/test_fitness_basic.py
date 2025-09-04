#!/usr/bin/env python3
"""
Basic fitness implementation test

Tests the fitness system without requiring full database setup.
"""

import sys
import os

# Add the backend directory to the Python path
sys.path.insert(0, '/home/david/Sara-jarvis/backend')

def test_imports():
    """Test that all fitness modules can be imported"""
    print("🧪 Testing fitness module imports...")
    
    try:
        # Test route imports
        print("  ✅ Testing routes...")
        from app.routes import fitness
        print("     - fitness routes: OK")
        
        # Test service imports  
        print("  ✅ Testing services...")
        from app.services.fitness import generator_service
        print("     - generator service: OK")
        
        from app.services.fitness import readiness_service
        print("     - readiness service: OK")
        
        from app.services.fitness import onboarding_service
        print("     - onboarding service: OK")
        
        from app.services.fitness import healthkit_service
        print("     - healthkit service: OK")
        
        from app.services.fitness import manual_entry_service
        print("     - manual entry service: OK")
        
        from app.services.fitness import baseline_learning
        print("     - baseline learning: OK")
        
        from app.services.fitness import adjustment_service
        print("     - adjustment service: OK")
        
        from app.services.fitness import notification_service
        print("     - notification service: OK")
        
        print("  ✅ All fitness modules imported successfully!")
        return True
        
    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False

def test_service_initialization():
    """Test that services can be initialized"""
    print("\n🧪 Testing service initialization...")
    
    try:
        from app.services.fitness.generator_service import FitnessPlanGenerator
        generator = FitnessPlanGenerator()
        print("  ✅ FitnessPlanGenerator initialized")
        
        from app.services.fitness.healthkit_service import HealthKitService  
        healthkit = HealthKitService()
        print("  ✅ HealthKitService initialized")
        
        from app.services.fitness.manual_entry_service import ManualEntryService
        manual = ManualEntryService()
        print("  ✅ ManualEntryService initialized")
        
        from app.services.fitness.baseline_learning import BaselineLearningEngine
        baseline = BaselineLearningEngine()
        print("  ✅ BaselineLearningEngine initialized")
        
        from app.services.fitness.adjustment_service import WorkoutAdjustmentService
        adjustment = WorkoutAdjustmentService()
        print("  ✅ WorkoutAdjustmentService initialized")
        
        from app.services.fitness.notification_service import FitnessNotificationService
        notification = FitnessNotificationService()
        print("  ✅ FitnessNotificationService initialized")
        
        print("  ✅ All services initialized successfully!")
        return True
        
    except Exception as e:
        print(f"  ❌ Service initialization error: {e}")
        return False

def test_route_registration():
    """Test that routes are properly structured"""
    print("\n🧪 Testing route structure...")
    
    try:
        from app.routes.fitness import router
        
        # Get all routes from the router
        routes = []
        for route in router.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                for method in route.methods:
                    if method != 'HEAD':  # Skip HEAD methods
                        routes.append(f"{method} {route.path}")
        
        print(f"  ✅ Found {len(routes)} fitness endpoints:")
        
        # Group by category
        categories = {
            'onboarding': [],
            'readiness': [], 
            'healthkit': [],
            'manual-entry': [],
            'baselines': [],
            'adjustments': [],
            'notifications': [],
            'other': []
        }
        
        for route in sorted(routes):
            categorized = False
            for category in categories.keys():
                if category in route.lower():
                    categories[category].append(route)
                    categorized = True
                    break
            if not categorized:
                categories['other'].append(route)
        
        for category, routes_list in categories.items():
            if routes_list:
                print(f"     {category}: {len(routes_list)} endpoints")
                for route in routes_list[:3]:  # Show first 3
                    print(f"       - {route}")
                if len(routes_list) > 3:
                    print(f"       - ... and {len(routes_list) - 3} more")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Route structure error: {e}")
        return False

def test_templates_and_configs():
    """Test that template and configuration systems work"""
    print("\n🧪 Testing templates and configurations...")
    
    try:
        # Test fitness plan generator
        from app.services.fitness.generator_service import FitnessPlanGenerator
        generator = FitnessPlanGenerator()
        
        # Test template selection
        test_profile = {
            "profile": {"demographics": {"experience": "beginner"}},
            "goals": {"goal_type": "general"},
            "days_per_week": 3,
            "session_len_min": 60
        }
        
        template = generator._select_template(test_profile)
        print(f"  ✅ Template selection works - got template with {len(template.get('days', []))} days")
        
        # Test healthkit config
        from app.services.fitness.healthkit_service import HealthKitService
        healthkit = HealthKitService()
        config = healthkit.get_healthkit_config("test_user")
        
        if hasattr(config, '__await__'):  # If it's a coroutine
            print("  ⚠️ HealthKit config is async - would need async context to test")
        else:
            print(f"  ✅ HealthKit config works - {len(config.get('required_permissions', []))} required permissions")
        
        # Test manual entry templates
        from app.services.fitness.manual_entry_service import ManualEntryService
        manual = ManualEntryService()
        
        template = manual.get_manual_entry_template("readiness")
        if hasattr(template, '__await__'):
            print("  ⚠️ Manual entry template is async - would need async context to test")
        else:
            print(f"  ✅ Manual entry template works")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Template/config error: {e}")
        return False

def main():
    """Run all tests"""
    print("🏋️ Sara Fitness System - Basic Implementation Test\n")
    
    tests = [
        test_imports,
        test_service_initialization, 
        test_route_registration,
        test_templates_and_configs
    ]
    
    passed = 0
    total = len(tests)
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ Test {test_func.__name__} crashed: {e}")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All basic tests passed! The fitness implementation looks ready.")
        print("\n📝 Next steps:")
        print("   1. Run database migrations to create fitness tables")
        print("   2. Start the FastAPI server")
        print("   3. Test endpoints with HTTP requests")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)