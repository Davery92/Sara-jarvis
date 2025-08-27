import React, { useState, useCallback, useEffect } from 'react';
// import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Loader2, Heart, Brain, Target, ArrowRight, CheckCircle } from 'lucide-react';
import { APP_CONFIG } from '../../config';

interface Question {
  id: string;
  question: string;
  type: 'text' | 'choice' | 'multi_choice' | 'timezone' | 'time_range';
  options?: string[];
  labels?: string[];
  follow_up?: boolean;
}

interface GTKYResponse {
  status: string;
  session_id?: string;
  message?: string;
  pack_info?: {
    name: string;
    description: string;
    progress?: string;
  };
  question?: Question;
  sprite_state?: string;
  completed_at?: string;
  can_retake?: boolean;
  follow_up?: string;
  progress?: string;
  completed_pack?: string;
  next_pack?: {
    id: string;
    name: string;
    description: string;
  };
  can_continue?: boolean;
  profile_summary?: string;
  next_steps?: string[];
}

interface GTKYInterviewProps {
  onComplete?: (profileSummary: string) => void;
  onSpriteStateChange?: (state: string) => void;
  personalityMode?: string;
}

export function GTKYInterview({ 
  onComplete, 
  onSpriteStateChange, 
  personalityMode = 'companion' 
}: GTKYInterviewProps) {
  const [currentResponse, setCurrentResponse] = useState<GTKYResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [currentAnswer, setCurrentAnswer] = useState<any>('');

  // Start the interview
  const startInterview = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/onboarding/gtky/start?personality_mode=${personalityMode}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to start interview: ${response.statusText}`);
      }
      
      const data: GTKYResponse = await response.json();
      setCurrentResponse(data);
      
      if (data.session_id) {
        setSessionId(data.session_id);
      }
      
      if (data.sprite_state && onSpriteStateChange) {
        onSpriteStateChange(data.sprite_state);
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start interview');
    } finally {
      setLoading(false);
    }
  }, [personalityMode, onSpriteStateChange]);

  // Submit an answer
  const submitAnswer = useCallback(async (answer: any) => {
    if (!sessionId || !currentResponse?.question) return;
    
    console.log('🔄 Submitting answer:', answer, 'for question:', currentResponse.question.id);
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/onboarding/gtky/respond/${sessionId}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          response: {
            question_id: currentResponse.question.id,
            value: answer,
            timestamp: new Date().toISOString()
          }
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to submit answer: ${response.statusText}`);
      }
      
      const data: GTKYResponse = await response.json();
      console.log('✅ Received response:', data);
      setCurrentResponse(data);
      
      // Save the answer
      if (currentResponse.question) {
        setAnswers(prev => ({
          ...prev,
          [currentResponse.question!.id]: answer
        }));
      }
      
      // Clear current answer for next question
      setCurrentAnswer('');
      
      // If interview is complete
      if (data.status === 'complete' && data.profile_summary && onComplete) {
        onComplete(data.profile_summary);
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setLoading(false);
    }
  }, [sessionId, currentResponse?.question, onComplete]);

  // Continue with next pack
  const continueWithPack = useCallback(async (packId: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/onboarding/gtky/continue/${packId}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Failed to continue with pack: ${response.statusText}`);
      }
      
      const data: GTKYResponse = await response.json();
      console.log('🔄 Continue pack response:', data);
      setCurrentResponse(data);
      
      if (data.session_id) {
        console.log('🆔 Updating session ID from', sessionId, 'to', data.session_id);
        setSessionId(data.session_id);
      }
      
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to continue with pack');
    } finally {
      setLoading(false);
    }
  }, []);

  // Start interview on mount
  useEffect(() => {
    startInterview();
  }, []); // Empty dependency array to run only once

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
            placeholder="Share your thoughts..."
            className="min-h-[100px] resize-none"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && e.ctrlKey && currentAnswer.trim()) {
                submitAnswer(currentAnswer.trim());
              }
            }}
          />
        );

      case 'choice':
        return (
          <div className="space-y-3">
            {question.options?.map((option, index) => (
              <Button
                key={option}
                variant={currentAnswer === option ? "default" : "outline"}
                className="w-full justify-start text-left h-auto py-3 px-4"
                onClick={() => setCurrentAnswer(option)}
              >
                <div>
                  <div className="font-medium">
                    {question.labels?.[index] || option}
                  </div>
                  {question.labels?.[index] && (
                    <div className="text-sm opacity-70 mt-1">
                      {option}
                    </div>
                  )}
                </div>
              </Button>
            ))}
          </div>
        );

      case 'multi_choice':
        return (
          <div className="space-y-3">
            {question.options?.map((option) => {
              const selected = Array.isArray(currentAnswer) 
                ? currentAnswer.includes(option)
                : false;
              
              return (
                <Button
                  key={option}
                  variant={selected ? "default" : "outline"}
                  className="w-full justify-start"
                  onClick={() => {
                    const current = Array.isArray(currentAnswer) ? currentAnswer : [];
                    if (selected) {
                      setCurrentAnswer(current.filter(a => a !== option));
                    } else {
                      setCurrentAnswer([...current, option]);
                    }
                  }}
                >
                  {option}
                  {selected && <CheckCircle className="ml-2 h-4 w-4" />}
                </Button>
              );
            })}
          </div>
        );

      case 'timezone':
        return (
          <Input
            type="text"
            value={currentAnswer}
            onChange={(e) => setCurrentAnswer(e.target.value)}
            placeholder="e.g., America/New_York, Europe/London, Asia/Tokyo"
          />
        );

      case 'time_range':
        return (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium">Start time</label>
                <Input
                  type="time"
                  value={currentAnswer?.start || ''}
                  onChange={(e) => setCurrentAnswer(prev => ({
                    ...prev,
                    start: e.target.value
                  }))}
                />
              </div>
              <div>
                <label className="text-sm font-medium">End time</label>
                <Input
                  type="time"
                  value={currentAnswer?.end || ''}
                  onChange={(e) => setCurrentAnswer(prev => ({
                    ...prev,
                    end: e.target.value
                  }))}
                />
              </div>
            </div>
            <p className="text-sm text-gray-400">
              Leave blank if you don't have specific quiet hours
            </p>
          </div>
        );

      default:
        return (
          <Input
            value={currentAnswer}
            onChange={(e) => setCurrentAnswer(e.target.value)}
            placeholder="Your answer..."
          />
        );
    }
  };

  // Check if current answer is valid for submission
  const canSubmit = () => {
    if (!currentAnswer) return false;
    
    const question = currentResponse?.question;
    if (!question) return false;

    switch (question.type) {
      case 'text':
        return typeof currentAnswer === 'string' && currentAnswer.trim().length > 0;
      case 'choice':
        return typeof currentAnswer === 'string' && currentAnswer.length > 0;
      case 'multi_choice':
        return Array.isArray(currentAnswer) && currentAnswer.length > 0;
      case 'timezone':
        return typeof currentAnswer === 'string' && currentAnswer.trim().length > 0;
      case 'time_range':
        return true; // Allow empty for optional quiet hours
      default:
        return true;
    }
  };

  const getPackIcon = (packName: string) => {
    switch (packName.toLowerCase()) {
      case 'getting to know you':
        return <Heart className="h-5 w-5" />;
      case 'your preferences':
        return <Brain className="h-5 w-5" />;
      case 'your goals & aspirations':
        return <Target className="h-5 w-5" />;
      default:
        return <Heart className="h-5 w-5" />;
    }
  };

  if (loading && !currentResponse) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-gray-400">Starting your get-to-know-you interview...</p>
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
            <Button onClick={startInterview}>Try Again</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Already completed
  if (currentResponse?.status === 'already_completed') {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardContent className="pt-6">
          <div className="text-center">
            <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Interview Already Completed!</h3>
            <p className="text-gray-400 mb-4">{currentResponse.message}</p>
            {currentResponse.can_retake && (
              <Button onClick={startInterview}>Retake Interview</Button>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  // Pack completed, show next pack option
  if (currentResponse?.status === 'pack_complete') {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardContent className="pt-6">
          <div className="text-center">
            <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">
              {currentResponse.completed_pack} Complete!
            </h3>
            
            {currentResponse.follow_up && (
              <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4 mb-6 text-left">
                <p className="text-blue-300">{currentResponse.follow_up}</p>
              </div>
            )}

            {currentResponse.next_pack && (
              <div className="space-y-4">
                <div className="border rounded-lg p-4 text-left">
                  <div className="flex items-center gap-2 mb-2">
                    {getPackIcon(currentResponse.next_pack.name)}
                    <h4 className="font-semibold">{currentResponse.next_pack.name}</h4>
                  </div>
                  <p className="text-gray-400 text-sm">
                    {currentResponse.next_pack.description}
                  </p>
                </div>
                
                <div className="flex gap-3">
                  <Button 
                    onClick={() => continueWithPack(currentResponse.next_pack!.id)}
                    className="flex-1"
                  >
                    Continue
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                  <Button variant="outline" onClick={() => window.location.reload()}>
                    Finish Later
                  </Button>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  // Interview complete
  if (currentResponse?.status === 'complete') {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardContent className="pt-6">
          <div className="text-center">
            <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Interview Complete!</h3>
            
            {currentResponse.profile_summary && (
              <div className="bg-green-900/30 border border-green-700/50 rounded-lg p-4 mb-6 text-left">
                <p className="text-green-300">{currentResponse.profile_summary}</p>
              </div>
            )}

            {currentResponse.follow_up && (
              <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4 mb-6 text-left">
                <p className="text-blue-300">{currentResponse.follow_up}</p>
              </div>
            )}

            {currentResponse.next_steps && (
              <div className="text-left">
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
          </div>
        </CardContent>
      </Card>
    );
  }

  // Show question
  const question = currentResponse?.question;
  const packInfo = currentResponse?.pack_info;

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader>
        <div className="flex items-center gap-3">
          {packInfo && getPackIcon(packInfo.name)}
          <div className="flex-1">
            <CardTitle className="text-lg">
              {packInfo?.name || 'Get to Know You'}
            </CardTitle>
            {packInfo?.description && (
              <p className="text-sm text-gray-400 mt-1">
                {packInfo.description}
              </p>
            )}
          </div>
          {packInfo?.progress && (
            <Badge variant="secondary">{packInfo.progress}</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {question && (
          <div className="space-y-4">
              <h3 className="text-lg font-medium leading-relaxed">
                {question.question}
              </h3>

              {renderInput()}

              {currentResponse?.follow_up && (
                <div className="bg-blue-900/30 border border-blue-700/50 rounded-lg p-4">
                  <p className="text-blue-300">{currentResponse.follow_up}</p>
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
                      Submitting...
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