import React, { useState, useCallback, useEffect } from 'react';
// import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Loader2, Moon, Star, Heart, ArrowRight, CheckCircle } from 'lucide-react';
import { APP_CONFIG } from '../../config';

interface ReflectionQuestion {
  id: string;
  question: string;
  type: 'text' | 'scale';
  scale?: {
    min: number;
    max: number;
    labels: Record<string, string>;
  };
  required?: boolean;
  follow_up?: boolean;
}

interface ReflectionResponse {
  status: string;
  reflection_id?: string;
  message?: string;
  reflection_date?: string;
  current_question_index?: number;
  total_questions?: number;
  question?: ReflectionQuestion;
  progress?: string;
  estimated_time?: string;
  responses?: Record<string, any>;
  insights_generated?: Record<string, any>;
  mood_score?: number;
  can_update?: boolean;
  follow_up?: string;
  insights?: Record<string, any>;
  reflection_summary?: string;
  next_steps?: string[];
}

interface NightlyReflectionProps {
  onComplete?: (insights: Record<string, any>) => void;
  onSpriteStateChange?: (state: string) => void;
  reflectionDate?: string;
}

export function NightlyReflection({ 
  onComplete, 
  onSpriteStateChange,
  reflectionDate
}: NightlyReflectionProps) {
  const [currentResponse, setCurrentResponse] = useState<ReflectionResponse | null>(null);
  const [reflectionId, setReflectionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentAnswer, setCurrentAnswer] = useState<any>('');

  // Start the reflection
  const startReflection = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const url = reflectionDate 
        ? `${APP_CONFIG.apiUrl}/reflection/start?reflection_date=${reflectionDate}`
        : `${APP_CONFIG.apiUrl}/reflection/start`;
        
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to start reflection: ${response.statusText}`);
      }
      
      const data: ReflectionResponse = await response.json();
      setCurrentResponse(data);
      
      if (data.reflection_id) {
        setReflectionId(data.reflection_id);
      }
      
      if (onSpriteStateChange) {
        onSpriteStateChange('reflecting');
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start reflection');
    } finally {
      setLoading(false);
    }
  }, [reflectionDate, onSpriteStateChange]);

  // Submit an answer
  const submitAnswer = useCallback(async (answer: any) => {
    if (!reflectionId || !currentResponse?.question || currentResponse.current_question_index === undefined) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/reflection/${reflectionId}/respond`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question_id: currentResponse.question.id,
          response: answer,
          question_index: currentResponse.current_question_index
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to submit answer: ${response.statusText}`);
      }
      
      const data: ReflectionResponse = await response.json();
      setCurrentResponse(data);
      
      // Clear current answer for next question
      setCurrentAnswer('');
      
      // If reflection is complete
      if (data.status === 'complete' && data.insights && onComplete) {
        onComplete(data.insights);
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setLoading(false);
    }
  }, [reflectionId, currentResponse?.question, currentResponse?.current_question_index, onComplete]);

  // Start reflection on mount
  useEffect(() => {
    startReflection();
  }, [startReflection]);

  // Render input based on question type
  const renderInput = () => {
    const question = currentResponse?.question;
    if (!question) return null;

    switch (question.type) {
      case 'text':
        return (
          <Textarea
            value={currentAnswer}
            onChange={(e) => setCurrentAnswer(e.target.value)}
            placeholder="Take your time... there's no right or wrong answer."
            className="min-h-[120px] resize-none"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && e.ctrlKey && currentAnswer.trim()) {
                submitAnswer(currentAnswer.trim());
              }
            }}
          />
        );

      case 'scale':
        const scale = question.scale;
        if (!scale) return null;
        
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-sm text-gray-400">
              <span>{scale.labels[scale.min.toString()] || scale.min}</span>
              <span>{scale.labels[scale.max.toString()] || scale.max}</span>
            </div>
            
            <div className="flex items-center justify-between">
              {Array.from({ length: scale.max - scale.min + 1 }, (_, i) => {
                const value = scale.min + i;
                const isSelected = currentAnswer === value;
                
                return (
                  <button
                    key={value}
                    onClick={() => setCurrentAnswer(value)}
                    className={`w-10 h-10 rounded-full border-2 transition-all ${
                      isSelected 
                        ? 'bg-blue-600 border-blue-600 text-white' 
                        : 'border-gray-300 hover:border-blue-400 text-gray-400'
                    }`}
                  >
                    {value}
                  </button>
                );
              })}
            </div>
            
            {scale.labels[currentAnswer?.toString()] && (
              <div className="text-center text-sm text-gray-400">
                {scale.labels[currentAnswer.toString()]}
              </div>
            )}
          </div>
        );

      default:
        return (
          <Input
            value={currentAnswer}
            onChange={(e) => setCurrentAnswer(e.target.value)}
            placeholder="Your thoughts..."
          />
        );
    }
  };

  // Check if current answer is valid for submission
  const canSubmit = () => {
    if (currentAnswer === '' || currentAnswer === null || currentAnswer === undefined) return false;
    
    const question = currentResponse?.question;
    if (!question) return false;

    switch (question.type) {
      case 'text':
        return typeof currentAnswer === 'string' && currentAnswer.trim().length > 0;
      case 'scale':
        return typeof currentAnswer === 'number' && currentAnswer >= (question.scale?.min || 1);
      default:
        return true;
    }
  };

  if (loading && !currentResponse) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Moon className="h-8 w-8 animate-pulse mx-auto mb-4 text-blue-500" />
          <p className="text-gray-400">Preparing your evening reflection...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardContent className="pt-6">
          <div className="text-center">
            <p className="text-red-600 mb-4">{error}</p>
            <Button onClick={startReflection}>Try Again</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Already completed today
  if (currentResponse?.status === 'existing') {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 bg-gradient-to-br from-purple-500 to-blue-600 p-3 rounded-full w-fit">
            <CheckCircle className="h-8 w-8 text-white" />
          </div>
          <CardTitle className="text-xl">Already Reflected Today!</CardTitle>
        </CardHeader>
        
        <CardContent className="space-y-4">
          <p className="text-center text-gray-400">{currentResponse.message}</p>
          
          {currentResponse.mood_score && (
            <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4 text-center">
              <p className="text-blue-300">
                Today's mood: <strong>{currentResponse.mood_score}/10</strong>
              </p>
            </div>
          )}

          {currentResponse.can_update && (
            <div className="flex gap-3 justify-center">
              <Button onClick={startReflection}>Update Reflection</Button>
              <Button variant="outline" onClick={() => window.location.reload()}>
                View Insights
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // Reflection complete
  if (currentResponse?.status === 'complete') {
    const insights = currentResponse.insights;
    
    return (
      <Card className="max-w-2xl mx-auto">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 bg-gradient-to-br from-purple-500 to-blue-600 p-3 rounded-full w-fit">
            <Star className="h-8 w-8 text-white" />
          </div>
          <CardTitle className="text-xl">Reflection Complete!</CardTitle>
        </CardHeader>
        
        <CardContent className="space-y-6">
          {currentResponse.message && (
            <p className="text-center text-gray-400">{currentResponse.message}</p>
          )}

          {currentResponse.follow_up && (
            <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4">
              <p className="text-blue-300">{currentResponse.follow_up}</p>
            </div>
          )}

          {insights && (
            <div className="space-y-4">
              {insights.appreciation && (
                <div className="bg-green-900/30 border border-green-700/50 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Heart className="h-5 w-5 text-green-400" />
                    <h4 className="font-semibold text-green-300">Appreciation</h4>
                  </div>
                  <p className="text-green-300">{insights.appreciation}</p>
                </div>
              )}

              {insights.insights && insights.insights.length > 0 && (
                <div className="bg-purple-900/30 border border-purple-700/50 rounded-lg p-4">
                  <h4 className="font-semibold text-purple-300 mb-2">Today's Insights</h4>
                  <ul className="space-y-2">
                    {insights.insights.map((insight: string, index: number) => (
                      <li key={index} className="text-purple-300 flex items-start gap-2">
                        <Star className="h-4 w-4 mt-0.5 flex-shrink-0" />
                        {insight}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {insights.tomorrow_suggestions && insights.tomorrow_suggestions.length > 0 && (
                <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4">
                  <h4 className="font-semibold text-blue-300 mb-2">Tomorrow's Focus</h4>
                  <ul className="space-y-2">
                    {insights.tomorrow_suggestions.map((suggestion: string, index: number) => (
                      <li key={index} className="text-blue-300 flex items-start gap-2">
                        <ArrowRight className="h-4 w-4 mt-0.5 flex-shrink-0" />
                        {suggestion}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {insights.gentle_reminder && (
                <div className="bg-amber-900/30 border border-amber-700/50 rounded-lg p-4">
                  <p className="text-amber-300">{insights.gentle_reminder}</p>
                </div>
              )}
            </div>
          )}

          {currentResponse.next_steps && (
            <div className="border-t pt-4">
              <h4 className="font-semibold mb-2">What's next:</h4>
              <ul className="space-y-1 text-sm text-gray-400">
                {currentResponse.next_steps.map((step, index) => (
                  <li key={index} className="flex items-start gap-2">
                    <CheckCircle className="h-4 w-4 text-green-500 mt-0.5 flex-shrink-0" />
                    {step}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // Show question
  const question = currentResponse?.question;

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader className="text-center">
        <div className="mx-auto mb-4 bg-gradient-to-br from-purple-500 to-blue-600 p-3 rounded-full w-fit">
          <Moon className="h-8 w-8 text-white" />
        </div>
        <CardTitle className="text-xl">Evening Reflection</CardTitle>
        <p className="text-sm text-gray-400 mt-2">
          Take a moment to reflect on your day
        </p>
        {currentResponse?.progress && (
          <Badge variant="secondary" className="mx-auto mt-2">
            {currentResponse.progress}
          </Badge>
        )}
      </CardHeader>

      <CardContent className="space-y-6">
        {question && (
          <div className="space-y-4">
              <h3 className="text-lg font-medium leading-relaxed text-center">
                {question.question}
              </h3>

              {renderInput()}

              {currentResponse?.follow_up && (
                <div className="bg-purple-900/30 border border-purple-700/50 rounded-lg p-4">
                  <p className="text-purple-300">{currentResponse.follow_up}</p>
                </div>
              )}

              <div className="flex gap-3">
                <Button
                  onClick={() => submitAnswer(currentAnswer)}
                  disabled={!canSubmit() || loading}
                  className="flex-1"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Reflecting...
                    </>
                  ) : (
                    <>
                      Continue
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </>
                  )}
                </Button>

                {question.type === 'text' && (
                  <div className="text-xs text-gray-500 flex items-end pb-2">
                    Ctrl+Enter to submit
                  </div>
                )}
              </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}