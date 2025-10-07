/**
 * Voice Agent Download Page
 * Allows users to download Windows and macOS voice control agents
 */
import React, { useState, useEffect } from 'react';
import { apiClient } from '../api/client';

interface Platform {
  platform: string;
  version: string;
  filename: string;
  size_mb: number;
  download_url: string;
  requirements: string;
  format: string;
}

interface DownloadInfo {
  version: string;
  platforms: {
    windows?: Platform;
    macos?: Platform;
  };
  features?: string[];
  setup_required?: string[];
  error?: string;
  message?: string;
}

const VoiceAgentDownload: React.FC = () => {
  const [downloadInfo, setDownloadInfo] = useState<DownloadInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    fetchDownloadInfo();
  }, []);

  const fetchDownloadInfo = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/api/agent/downloads/info');
      setDownloadInfo(response.data);
      setError(null);
    } catch (err: any) {
      console.error('Error fetching download info:', err);
      setError(err.response?.data?.message || 'Failed to fetch download information');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (url: string, platform: string) => {
    try {
      setDownloading(platform);

      // Track download
      await apiClient.post('/api/agent/downloads/track', {
        platform,
        version: downloadInfo?.version || 'unknown'
      });

      // Open download URL
      window.open(url, '_blank');
    } catch (err) {
      console.error('Download tracking failed:', err);
      // Still open download even if tracking fails
      window.open(url, '_blank');
    } finally {
      setTimeout(() => setDownloading(null), 1000);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-black">
        <div className="text-green-400 text-xl">Loading download information...</div>
      </div>
    );
  }

  if (error || downloadInfo?.error) {
    return (
      <div className="min-h-screen bg-black p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-900/20 border border-red-500 rounded-lg p-6">
            <h2 className="text-red-400 text-2xl font-bold mb-4">⚠️ Download Not Available</h2>
            <p className="text-red-300 mb-4">{error || downloadInfo?.message}</p>
            {downloadInfo?.message && (
              <div className="mt-4 p-4 bg-gray-900 rounded">
                <p className="text-gray-400 text-sm font-mono">{downloadInfo.message}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-12 text-center">
          <h1 className="text-4xl font-bold text-green-400 mb-4">
            🎙️ Sara Voice Agent
          </h1>
          <p className="text-xl text-gray-300 mb-2">
            Voice control for Shadow Mode and Sara Assistant
          </p>
          <p className="text-sm text-gray-500">
            Version {downloadInfo?.version}
          </p>
        </div>

        {/* Features */}
        {downloadInfo?.features && (
          <div className="mb-12 bg-gray-900 border border-gray-700 rounded-lg p-6">
            <h2 className="text-2xl font-bold text-green-400 mb-4">✨ Features</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {downloadInfo.features.map((feature, index) => (
                <div key={index} className="flex items-start">
                  <span className="text-green-400 mr-2">✓</span>
                  <span className="text-gray-300">{feature}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Download Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
          {/* Windows */}
          {downloadInfo?.platforms?.windows && (
            <div className="bg-gray-900 border border-blue-500 rounded-lg p-6 hover:border-blue-400 transition-colors">
              <div className="flex items-center mb-4">
                <span className="text-4xl mr-4">🪟</span>
                <div>
                  <h3 className="text-2xl font-bold text-blue-400">Windows</h3>
                  <p className="text-sm text-gray-400">
                    {downloadInfo.platforms.windows.requirements}
                  </p>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-gray-300 mb-2">
                  <strong>File:</strong> {downloadInfo.platforms.windows.filename}
                </p>
                <p className="text-gray-300 mb-2">
                  <strong>Size:</strong> {downloadInfo.platforms.windows.size_mb} MB
                </p>
                <p className="text-gray-300 text-sm">
                  {downloadInfo.platforms.windows.format}
                </p>
              </div>

              <button
                onClick={() => handleDownload(
                  downloadInfo.platforms.windows.download_url,
                  'windows'
                )}
                disabled={downloading === 'windows'}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-wait text-white font-bold py-3 px-6 rounded-lg transition-colors"
              >
                {downloading === 'windows' ? 'Downloading...' : '⬇️ Download for Windows'}
              </button>

              <div className="mt-4 text-xs text-gray-500">
                <p>• Download single .exe file</p>
                <p>• Run SaraShadowAgent-Installer.exe</p>
                <p>• Grant microphone permissions</p>
                <p>• No installation required!</p>
              </div>
            </div>
          )}

          {/* macOS */}
          {downloadInfo?.platforms?.macos && (
            <div className="bg-gray-900 border border-purple-500 rounded-lg p-6 hover:border-purple-400 transition-colors">
              <div className="flex items-center mb-4">
                <span className="text-4xl mr-4">🍎</span>
                <div>
                  <h3 className="text-2xl font-bold text-purple-400">macOS</h3>
                  <p className="text-sm text-gray-400">
                    {downloadInfo.platforms.macos.requirements}
                  </p>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-gray-300 mb-2">
                  <strong>File:</strong> {downloadInfo.platforms.macos.filename}
                </p>
                <p className="text-gray-300 mb-2">
                  <strong>Size:</strong> {downloadInfo.platforms.macos.size_mb} MB
                </p>
                <p className="text-gray-300 text-sm">
                  {downloadInfo.platforms.macos.format}
                </p>
              </div>

              <button
                onClick={() => handleDownload(
                  downloadInfo.platforms.macos.download_url,
                  'macos'
                )}
                disabled={downloading === 'macos'}
                className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-purple-800 disabled:cursor-wait text-white font-bold py-3 px-6 rounded-lg transition-colors"
              >
                {downloading === 'macos' ? 'Downloading...' : '⬇️ Download for macOS'}
              </button>

              <div className="mt-4 text-xs text-gray-500">
                <p>• Download single .dmg file</p>
                <p>• Open installer and drag to Applications</p>
                <p>• Grant microphone permissions</p>
                <p>• Simple drag-and-drop installation!</p>
              </div>
            </div>
          )}
        </div>

        {/* Setup Requirements */}
        {downloadInfo?.setup_required && (
          <div className="bg-yellow-900/20 border border-yellow-500 rounded-lg p-6 mb-12">
            <h2 className="text-xl font-bold text-yellow-400 mb-4">⚙️ Setup Requirements</h2>
            <ul className="space-y-2">
              {downloadInfo.setup_required.map((req, index) => (
                <li key={index} className="text-yellow-200 flex items-start">
                  <span className="mr-2">•</span>
                  <span>{req}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Usage Guide */}
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-6">
          <h2 className="text-2xl font-bold text-green-400 mb-4">📖 Quick Start Guide</h2>

          <div className="space-y-4 text-gray-300">
            <div>
              <h3 className="text-lg font-bold text-green-300 mb-2">1. Installation</h3>
              <p className="text-sm text-gray-400">
                Download the agent for your platform, extract/install, and launch the application.
                Grant microphone permissions when prompted.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-bold text-green-300 mb-2">2. Wake Word Activation</h3>
              <p className="text-sm text-gray-400">
                Say <strong className="text-green-400">"sarah"</strong> to activate the voice agent.
                The system tray icon will change to indicate listening state.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-bold text-green-300 mb-2">3. Voice Modes</h3>
              <ul className="text-sm text-gray-400 space-y-1 ml-4">
                <li>• <strong>Always-On:</strong> Always listening for "sarah"</li>
                <li>• <strong>Shadow-Only:</strong> Only active during Shadow Mode sessions</li>
                <li>• <strong>Push-to-Talk:</strong> Manual activation from system tray</li>
              </ul>
            </div>

            <div>
              <h3 className="text-lg font-bold text-green-300 mb-2">4. Configuration</h3>
              <p className="text-sm text-gray-400">
                Right-click the system tray icon to access settings, change modes, view logs,
                and control the agent.
              </p>
            </div>
          </div>
        </div>

        {/* Back Button */}
        <div className="mt-8 text-center">
          <button
            onClick={() => window.history.back()}
            className="text-green-400 hover:text-green-300 transition-colors"
          >
            ← Back to Sara
          </button>
        </div>
      </div>
    </div>
  );
};

export default VoiceAgentDownload;
