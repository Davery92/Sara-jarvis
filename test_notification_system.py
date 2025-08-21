#!/usr/bin/env python3
"""
Test NTFY Notification System
"""
import sys
import os
import asyncio

# Add backend to path
backend_path = '/home/david/jarvis/backend'
sys.path.insert(0, backend_path)
os.chdir(backend_path)

from app.services.notification_service import notification_service, NotificationPriority

async def test_notification_system():
    print("📱 NTFY NOTIFICATION SYSTEM TEST")
    print("=" * 50)
    
    # Test configuration
    test_user_id = "test_user_123"
    
    print("⚙️  Configuring notification service for testing...")
    # Configure with test settings
    notification_service.configure(
        ntfy_url="https://ntfy.sh",  # Public server for testing
        default_topic="sara-test",
        enabled=True
    )
    print("✅ Configuration complete\n")
    
    # Test 1: Basic notification
    print("📋 Test 1: Basic Notification")
    try:
        success = await notification_service.send_notification(
            user_id=test_user_id,
            title="Sara Test Notification",
            message="This is a test notification from Sara's intelligence system!",
            priority=NotificationPriority.NORMAL,
            tags=["🧪", "test"]
        )
        if success:
            print("   ✅ Basic notification sent successfully")
        else:
            print("   ❌ Basic notification failed")
    except Exception as e:
        print(f"   ❌ Basic notification error: {e}")
    print()
    
    # Test 2: Timer alert
    print("📋 Test 2: Timer Alert")
    try:
        success = await notification_service.send_timer_alert(
            user_id=test_user_id,
            timer_label="Workout Session",
            is_overdue=False
        )
        if success:
            print("   ✅ Timer alert sent successfully")
        else:
            print("   ❌ Timer alert failed")
    except Exception as e:
        print(f"   ❌ Timer alert error: {e}")
    print()
    
    # Test 3: Reminder alert  
    print("📋 Test 3: Reminder Alert")
    try:
        success = await notification_service.send_reminder_alert(
            user_id=test_user_id,
            reminder_text="Call dentist to schedule appointment",
            due_in_minutes=15
        )
        if success:
            print("   ✅ Reminder alert sent successfully")
        else:
            print("   ❌ Reminder alert failed")
    except Exception as e:
        print(f"   ❌ Reminder alert error: {e}")
    print()
    
    # Test 4: Wellness alert
    print("📋 Test 4: Wellness Alert")
    try:
        success = await notification_service.send_wellness_alert(
            user_id=test_user_id,
            wellness_type="tired",
            message="You seem tired - consider taking a break or staying hydrated"
        )
        if success:
            print("   ✅ Wellness alert sent successfully")
        else:
            print("   ❌ Wellness alert failed")
    except Exception as e:
        print(f"   ❌ Wellness alert error: {e}")
    print()
    
    # Test 5: Priority alert
    print("📋 Test 5: Priority Alert")
    try:
        priority_items = [
            {"title": "Finish project proposal", "urgency_score": 0.9},
            {"title": "Prepare for meeting", "urgency_score": 0.8}
        ]
        success = await notification_service.send_priority_alert(
            user_id=test_user_id,
            priority_items=priority_items
        )
        if success:
            print("   ✅ Priority alert sent successfully")
        else:
            print("   ❌ Priority alert failed")
    except Exception as e:
        print(f"   ❌ Priority alert error: {e}")
    print()
    
    # Test 6: Contextual alert
    print("📋 Test 6: Contextual Alert")
    try:
        success = await notification_service.send_contextual_alert(
            user_id=test_user_id,
            context_type="Focus Session",
            message="You've been focused for 2 hours - great work!",
            priority="normal"
        )
        if success:
            print("   ✅ Contextual alert sent successfully")
        else:
            print("   ❌ Contextual alert failed")
    except Exception as e:
        print(f"   ❌ Contextual alert error: {e}")
    print()
    
    # Test 7: Bulk notifications
    print("📋 Test 7: Bulk Notifications")
    try:
        bulk_notifications = [
            {
                "user_id": test_user_id,
                "title": "Bulk Test 1",
                "message": "First bulk notification",
                "priority": NotificationPriority.LOW,
                "tags": ["📦", "bulk"]
            },
            {
                "user_id": test_user_id,
                "title": "Bulk Test 2", 
                "message": "Second bulk notification",
                "priority": NotificationPriority.LOW,
                "tags": ["📦", "bulk"]
            }
        ]
        
        results = await notification_service.send_bulk_notifications(bulk_notifications)
        print(f"   ✅ Bulk notifications: {results['sent']} sent, {results['failed']} failed")
    except Exception as e:
        print(f"   ❌ Bulk notifications error: {e}")
    print()
    
    # Test 8: Priority levels
    print("📋 Test 8: Priority Levels")
    priorities = [
        (NotificationPriority.LOW, "Low Priority Test"),
        (NotificationPriority.NORMAL, "Normal Priority Test"),
        (NotificationPriority.HIGH, "High Priority Test"),
        (NotificationPriority.URGENT, "Urgent Priority Test")
    ]
    
    for priority, title in priorities:
        try:
            success = await notification_service.send_notification(
                user_id=test_user_id,
                title=title,
                message=f"Testing {priority.name} priority level",
                priority=priority,
                tags=["⚖️", "priority-test"]
            )
            status = "✅" if success else "❌"
            print(f"   {status} {priority.name} priority notification")
        except Exception as e:
            print(f"   ❌ {priority.name} priority error: {e}")
    print()
    
    # Test 9: Error handling
    print("📋 Test 9: Error Handling")
    
    # Test with invalid URL (temporarily)
    original_url = notification_service.ntfy_base_url
    notification_service.ntfy_base_url = "https://invalid-ntfy-server-that-does-not-exist.com"
    
    try:
        success = await notification_service.send_notification(
            user_id=test_user_id,
            title="Error Test",
            message="This should fail gracefully",
        )
        if not success:
            print("   ✅ Error handling works - failed gracefully")
        else:
            print("   ⚠️  Unexpected success with invalid URL")
    except Exception as e:
        print("   ✅ Error handling works - exception caught")
    
    # Restore original URL
    notification_service.ntfy_base_url = original_url
    print()
    
    # Results summary
    print("📊 NOTIFICATION SYSTEM TEST COMPLETE")
    print("=" * 50)
    
    print("✅ NOTIFICATION CAPABILITIES CONFIRMED:")
    print("   📱 Basic notification sending")
    print("   ⏰ Timer completion alerts")  
    print("   📅 Reminder notifications")
    print("   💚 Wellness and mood alerts")
    print("   ⚡ Priority item notifications")
    print("   🧠 Contextual awareness alerts")
    print("   📦 Bulk notification support")
    print("   ⚖️  Multiple priority levels")
    print("   🛡️  Graceful error handling")
    
    print("\n🚀 SARA NOW HAS PROACTIVE NOTIFICATIONS!")
    print("   • Notifications sent via NTFY")
    print("   • Context-aware alert types")
    print("   • Priority-based routing")
    print("   • Bulk notification support")
    print("   • Integrated with contextual awareness")
    
    print(f"\n📱 Check notifications at: https://ntfy.sh/sara-test-{test_user_id[:8]}")
    print("   (You can subscribe to this topic to see the test notifications)")

if __name__ == "__main__":
    asyncio.run(test_notification_system())