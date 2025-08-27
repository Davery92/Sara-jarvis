import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Moon, Clock, Star } from 'lucide-react';
import { NightlyReflection } from './NightlyReflection';

interface ReflectionTriggerProps {
  onComplete?: () => void;
  onSpriteStateChange?: (state: string) => void;
}

export function ReflectionTrigger({ onComplete, onSpriteStateChange }: ReflectionTriggerProps) {
  const [showReflection, setShowReflection] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Update time every minute
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 60000);
    
    return () => clearInterval(timer);
  }, []);

  const handleComplete = (insights: Record<string, any>) => {
    console.log('Reflection completed:', insights);
    setShowReflection(false);
    if (onComplete) {
      onComplete();
    }
  };

  // Check if it's evening (after 6 PM)
  const isEvening = currentTime.getHours() >= 18;
  const timeGreeting = currentTime.getHours() >= 18 ? 'Good evening' : 'Hello';

  if (showReflection) {
    return (
      <NightlyReflection
        onComplete={handleComplete}
        onSpriteStateChange={onSpriteStateChange}
      />
    );
  }

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader className="text-center">
        <div className="mx-auto mb-4 bg-gradient-to-br from-purple-500 to-blue-600 p-3 rounded-full w-fit">
          <Moon className="h-8 w-8 text-white" />
        </div>
        <CardTitle className="text-2xl">{timeGreeting}! Ready to reflect?</CardTitle>
        <CardDescription className="text-base">
          Take a few minutes to reflect on your day and set intentions for tomorrow.
          This gentle practice helps build self-awareness and clarity.
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        <div className="grid gap-4">
          <div className="flex items-center gap-3 p-3 bg-purple-900/30 border border-purple-700/50 rounded-lg">
            <Clock className="h-5 w-5 text-purple-400" />
            <div className="text-sm text-gray-200">
              <strong>Quick & meaningful:</strong> Just 3-5 minutes of thoughtful reflection
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-blue-900/30 border border-blue-700/50 rounded-lg">
            <Star className="h-5 w-5 text-blue-400" />
            <div className="text-sm text-gray-200">
              <strong>Personal insights:</strong> Sara will generate personalized insights for tomorrow
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-green-900/30 border border-green-700/50 rounded-lg">
            <Moon className="h-5 w-5 text-green-400" />
            <div className="text-sm text-gray-200">
              <strong>Build the habit:</strong> Daily reflection helps you learn and grow over time
            </div>
          </div>
        </div>

        <div className="text-center space-y-4">
          <Button 
            onClick={() => setShowReflection(true)}
            size="lg"
            className="w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700"
          >
            Start Tonight's Reflection
          </Button>
          
          {!isEvening && (
            <p className="text-xs text-gray-400">
              Best reflected on in the evening, but available anytime
            </p>
          )}
          
          <Button variant="ghost" size="sm" className="text-gray-400 hover:text-gray-200">
            Skip tonight (you can reflect anytime in Settings)
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}