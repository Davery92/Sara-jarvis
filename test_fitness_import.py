#!/usr/bin/env python3
"""
Simple test script to verify the fitness implementation is working.
Tests import of all fitness modules and route registration.
"""

import sys
import os

# Add backend directory to Python path
sys.path.insert(0, '/home/david/Sara-jarvis/backend')

def test_fitness_imports():
    """Test that all fitness modules can be imported successfully."""
    print("🧪 Testing fitness module imports...")
    
    try:
        # Test models import
        from app.models.fitness import (
            FitnessProfile, FitnessGoal, FitnessPlan, Workout, WorkoutLog, 
            MorningReadiness, ReadinessBaseline, ReadinessAdjustment, FitnessEvent
        )
        print("✅ Fitness models imported successfully")
        
        # Test services imports
        from app.services.fitness.generator_service import FitnessPlanGenerator
        from app.services.fitness.readiness_service import ReadinessEngine  
        from app.services.fitness.onboarding_service import FitnessOnboardingService
        from app.services.fitness.healthkit_service import HealthKitService
        from app.services.fitness.manual_entry_service import ManualEntryService
        from app.services.fitness.baseline_learning import BaselineLearningEngine
        from app.services.fitness.adjustment_service import WorkoutAdjustmentService
        from app.services.fitness.notification_service import FitnessNotificationService
        from app.services.fitness.templates_library import FitnessTemplatesLibrary
        print("✅ Fitness services imported successfully")
        
        # Test routes import
        from app.routes.fitness import router
        print(f"✅ Fitness routes imported successfully: {len(router.routes)} endpoints")
        
        # Test tools import
        from app.tools.fitness import (
            save_fitness_profile, save_fitness_goals, propose_fitness_plan, 
            commit_fitness_plan, adjust_todays_workout
        )
        print("✅ Fitness tools imported successfully")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_route_definitions():
    """Test that fitness routes are properly defined."""
    print("\n🔍 Testing fitness route definitions...")
    
    try:
        from app.routes.fitness import router
        
        # Get all route paths
        routes = [route.path for route in router.routes]
        
        # Check for key routes
        expected_routes = [
            "/notifications/schedule",
            "/manual-entry/template/{entry_type}",
            "/healthkit/config", 
            "/onboarding/start",
            "/readiness/daily",
            "/baselines/status"
        ]
        
        missing_routes = []
        found_routes = []
        
        for expected in expected_routes:
            if expected in routes:
                found_routes.append(expected)
            else:
                missing_routes.append(expected)
        
        print(f"✅ Found {len(found_routes)} expected routes: {found_routes}")
        
        if missing_routes:
            print(f"⚠️  Missing routes: {missing_routes}")
        
        print(f"📊 Total routes: {len(routes)}")
        
        return len(missing_routes) == 0
        
    except Exception as e:
        print(f"❌ Route definition test failed: {e}")
        return False

def main():
    """Main test function."""
    print("🎯 Sara Fitness Module - Implementation Test")
    print("=" * 50)
    
    all_passed = True
    
    # Run import tests
    if not test_fitness_imports():
        all_passed = False
    
    # Run route tests  
    if not test_route_definitions():
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 ALL TESTS PASSED - FITNESS MODULE READY!")
        print("\nThe Sara Fitness module is successfully implemented and ready for integration.")
        print("Next steps:")
        print("1. Run database migration: alembic upgrade head")  
        print("2. Start server with fitness routes registered")
        print("3. Test endpoints with authentication")
        return 0
    else:
        print("❌ SOME TESTS FAILED - REVIEW IMPLEMENTATION")
        return 1

if __name__ == "__main__":
    exit(main())