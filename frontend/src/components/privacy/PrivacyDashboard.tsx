import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { 
  Shield, 
  Eye, 
  Download, 
  Trash2, 
  Settings, 
  User, 
  Brain, 
  MessageSquare, 
  FileText,
  Activity,
  BarChart3,
  Lock
} from 'lucide-react';
import { APP_CONFIG } from '../../config';

interface PrivacySettings {
  memory_retention_days: number;
  share_reflections_with_ai: boolean;
  autonomous_level: string;
  data_categories: Record<string, boolean>;
  export_enabled: boolean;
  analytics_enabled: boolean;
}

interface UserData {
  profile_data?: Record<string, any>;
  total_episodes?: number;
  total_reflections?: number;
  total_notes?: number;
  total_documents?: number;
  activity_logs?: any[];
  last_activity?: string;
}

interface PrivacyDashboardProps {
  onToast?: (message: string, type?: 'success' | 'error') => void;
}

export function PrivacyDashboard({ onToast }: PrivacyDashboardProps) {
  const [privacySettings, setPrivacySettings] = useState<PrivacySettings | null>(null);
  const [userData, setUserData] = useState<UserData | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  useEffect(() => {
    loadPrivacyData();
  }, []);

  const loadPrivacyData = async () => {
    try {
      setLoading(true);
      
      // Load privacy settings and user data in parallel
      const [settingsRes, dataRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/privacy/settings`, {
          credentials: 'include'
        }),
        fetch(`${APP_CONFIG.apiUrl}/privacy/data-summary`, {
          credentials: 'include'
        })
      ]);

      if (settingsRes.ok) {
        const settings = await settingsRes.json();
        setPrivacySettings(settings);
      }

      if (dataRes.ok) {
        const data = await dataRes.json();
        setUserData(data);
      }
    } catch (error) {
      console.error('Failed to load privacy data:', error);
      if (onToast) {
        onToast('Failed to load privacy settings', 'error');
      }
    } finally {
      setLoading(false);
    }
  };

  const updatePrivacySetting = async (key: string, value: any) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/privacy/settings`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ [key]: value })
      });

      if (response.ok) {
        setPrivacySettings(prev => prev ? { ...prev, [key]: value } : null);
        if (onToast) {
          onToast('Privacy setting updated', 'success');
        }
      }
    } catch (error) {
      console.error('Failed to update setting:', error);
      if (onToast) {
        onToast('Failed to update setting', 'error');
      }
    }
  };

  const exportData = async () => {
    try {
      setExporting(true);
      
      const response = await fetch(`${APP_CONFIG.apiUrl}/privacy/export`, {
        method: 'POST',
        credentials: 'include'
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `sara-data-export-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        if (onToast) {
          onToast('Data exported successfully', 'success');
        }
      }
    } catch (error) {
      console.error('Failed to export data:', error);
      if (onToast) {
        onToast('Failed to export data', 'error');
      }
    } finally {
      setExporting(false);
    }
  };

  const deleteDataCategory = async (category: string) => {
    if (!confirm(`Are you sure you want to delete all ${category} data? This action cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/privacy/delete/${category}`, {
        method: 'DELETE',
        credentials: 'include'
      });

      if (response.ok) {
        if (onToast) {
          onToast(`${category} data deleted successfully`, 'success');
        }
        loadPrivacyData(); // Refresh data
      }
    } catch (error) {
      console.error(`Failed to delete ${category} data:`, error);
      if (onToast) {
        onToast(`Failed to delete ${category} data`, 'error');
      }
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              <span className="ml-3">Loading privacy dashboard...</span>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const renderOverview = () => (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Eye className="h-5 w-5" />
            Data Transparency
          </CardTitle>
          <CardDescription>
            See what data Sara has stored about you
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-blue-50 rounded-lg p-4">
              <MessageSquare className="h-6 w-6 text-blue-600 mb-2" />
              <div className="text-2xl font-bold">{userData?.total_episodes || 0}</div>
              <div className="text-sm text-gray-600">Episodes</div>
            </div>
            
            <div className="bg-purple-50 rounded-lg p-4">
              <Brain className="h-6 w-6 text-purple-600 mb-2" />
              <div className="text-2xl font-bold">{userData?.total_reflections || 0}</div>
              <div className="text-sm text-gray-600">Reflections</div>
            </div>
            
            <div className="bg-green-50 rounded-lg p-4">
              <FileText className="h-6 w-6 text-green-600 mb-2" />
              <div className="text-2xl font-bold">{userData?.total_notes || 0}</div>
              <div className="text-sm text-gray-600">Notes</div>
            </div>
            
            <div className="bg-orange-50 rounded-lg p-4">
              <FileText className="h-6 w-6 text-orange-600 mb-2" />
              <div className="text-2xl font-bold">{userData?.total_documents || 0}</div>
              <div className="text-sm text-gray-600">Documents</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            Quick Privacy Controls
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">Share reflections with AI</div>
              <div className="text-sm text-gray-600">Allow Sara to learn from your reflections</div>
            </div>
            <Button
              variant={privacySettings?.share_reflections_with_ai ? "default" : "outline"}
              size="sm"
              onClick={() => updatePrivacySetting('share_reflections_with_ai', !privacySettings?.share_reflections_with_ai)}
            >
              {privacySettings?.share_reflections_with_ai ? 'Enabled' : 'Disabled'}
            </Button>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">Analytics</div>
              <div className="text-sm text-gray-600">Help improve Sara through usage analytics</div>
            </div>
            <Button
              variant={privacySettings?.analytics_enabled ? "default" : "outline"}
              size="sm"
              onClick={() => updatePrivacySetting('analytics_enabled', !privacySettings?.analytics_enabled)}
            >
              {privacySettings?.analytics_enabled ? 'Enabled' : 'Disabled'}
            </Button>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">Autonomy Level</div>
              <div className="text-sm text-gray-600">How proactive Sara should be</div>
            </div>
            <Badge variant="secondary">
              {privacySettings?.autonomous_level || 'auto'}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  );

  const renderDataManagement = () => (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-5 w-5" />
            Export Your Data
          </CardTitle>
          <CardDescription>
            Download all your data in JSON format
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button 
            onClick={exportData} 
            disabled={exporting || !privacySettings?.export_enabled}
            className="w-full"
          >
            {exporting ? 'Exporting...' : 'Export All Data'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-red-600">
            <Trash2 className="h-5 w-5" />
            Delete Data
          </CardTitle>
          <CardDescription>
            Permanently delete specific types of data
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3">
            {[
              { key: 'episodes', label: 'Chat Episodes', desc: 'All conversation history' },
              { key: 'reflections', label: 'Reflections', desc: 'Daily reflection entries' },
              { key: 'notes', label: 'Notes', desc: 'All notes and connections' },
              { key: 'documents', label: 'Documents', desc: 'Uploaded files and content' }
            ].map(item => (
              <div key={item.key} className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <div className="font-medium">{item.label}</div>
                  <div className="text-sm text-gray-600">{item.desc}</div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => deleteDataCategory(item.key)}
                  className="text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  Delete
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );

  const renderSettings = () => (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lock className="h-5 w-5" />
            Data Retention
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">
              Memory retention (days)
            </label>
            <Input
              type="number"
              min="1"
              max="3650"
              value={privacySettings?.memory_retention_days || 365}
              onChange={(e) => updatePrivacySetting('memory_retention_days', parseInt(e.target.value))}
              className="w-32"
            />
            <p className="text-sm text-gray-600 mt-1">
              How long Sara keeps your data before archiving
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Autonomy Settings
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">
              Autonomous Level
            </label>
            <div className="space-y-2">
              {[
                { value: 'disabled', label: 'Disabled', desc: 'No autonomous actions' },
                { value: 'ask-first', label: 'Ask First', desc: 'Always ask before taking actions' },
                { value: 'auto', label: 'Automatic', desc: 'Take helpful actions automatically' }
              ].map(option => (
                <label key={option.value} className="flex items-center space-x-3">
                  <input
                    type="radio"
                    name="autonomy_level"
                    value={option.value}
                    checked={privacySettings?.autonomous_level === option.value}
                    onChange={(e) => updatePrivacySetting('autonomous_level', e.target.value)}
                    className="text-blue-600"
                  />
                  <div>
                    <div className="font-medium">{option.label}</div>
                    <div className="text-sm text-gray-600">{option.desc}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Shield className="h-6 w-6" />
          Privacy & Control
        </h1>
        <p className="text-gray-600 mt-2">
          Control your data, privacy settings, and how Sara learns from your interactions
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="flex space-x-1 mb-6 bg-gray-100 p-1 rounded-lg">
        {[
          { key: 'overview', label: 'Overview', icon: Eye },
          { key: 'data', label: 'Data Management', icon: Download },
          { key: 'settings', label: 'Settings', icon: Settings }
        ].map(tab => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 flex items-center justify-center gap-2 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && renderOverview()}
      {activeTab === 'data' && renderDataManagement()}
      {activeTab === 'settings' && renderSettings()}
    </div>
  );
}