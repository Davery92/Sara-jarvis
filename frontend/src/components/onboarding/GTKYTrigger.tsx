import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Heart, MessageCircle, Settings } from 'lucide-react';
import { GTKYInterview } from './GTKYInterview';

interface GTKYTriggerProps {
  onComplete?: () => void;
  onSpriteStateChange?: (state: string) => void;
  personalityMode?: string;
}

export function GTKYTrigger({ onComplete, onSpriteStateChange, personalityMode = 'companion' }: GTKYTriggerProps) {
  const [showInterview, setShowInterview] = useState(false);

  const handleComplete = (profileSummary: string) => {
    console.log('GTKY completed:', profileSummary);
    setShowInterview(false);
    if (onComplete) {
      onComplete();
    }
  };

  if (showInterview) {
    return (
      <GTKYInterview
        onComplete={handleComplete}
        onSpriteStateChange={onSpriteStateChange}
        personalityMode={personalityMode}
      />
    );
  }

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader className="text-center">
        <div className="mx-auto mb-4 bg-gradient-to-br from-blue-500 to-purple-600 p-3 rounded-full w-fit">
          <Heart className="h-8 w-8 text-white" />
        </div>
        <CardTitle className="text-2xl">Let's get to know each other!</CardTitle>
        <CardDescription className="text-base">
          Help Sara understand your preferences, goals, and how you'd like to work together. 
          This quick 5-minute conversation will personalize your experience.
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        <div className="grid gap-4">
          <div className="flex items-center gap-3 p-3 bg-blue-900/30 border border-blue-700/50 rounded-lg">
            <MessageCircle className="h-5 w-5 text-blue-400" />
            <div className="text-sm text-gray-200">
              <strong>Personal & natural:</strong> Sara will ask questions like a friendly conversation
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-green-900/30 border border-green-700/50 rounded-lg">
            <Settings className="h-5 w-5 text-green-400" />
            <div className="text-sm text-gray-200">
              <strong>Customized experience:</strong> Your answers will personalize how Sara works with you
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-3 bg-purple-900/30 border border-purple-700/50 rounded-lg">
            <Heart className="h-5 w-5 text-purple-400" />
            <div className="text-sm text-gray-200">
              <strong>Your privacy matters:</strong> You control what Sara remembers and how she uses your information
            </div>
          </div>
        </div>

        <div className="text-center space-y-4">
          <Button 
            onClick={() => setShowInterview(true)}
            size="lg"
            className="w-full bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700"
          >
            Start Interview
          </Button>
          
          <Button variant="ghost" size="sm" className="text-gray-400 hover:text-gray-200">
            Skip for now (you can do this later in Settings)
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}