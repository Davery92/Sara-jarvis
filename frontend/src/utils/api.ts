import { APP_CONFIG } from '../config';

interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: string;
  headers?: Record<string, string>;
}

/**
 * Make an authenticated API request
 */
export async function apiRequest<T = any>(
  endpoint: string, 
  options: ApiRequestOptions = {}
): Promise<T> {
  const { method = 'GET', body, headers = {} } = options;
  
  // Get auth token from localStorage (this is how the existing app handles auth)
  const token = localStorage.getItem('token');
  
  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers
  };

  if (token) {
    requestHeaders['Authorization'] = `Bearer ${token}`;
  }

  const url = endpoint.startsWith('http') 
    ? endpoint 
    : `${APP_CONFIG.apiUrl}${endpoint}`;

  const response = await fetch(url, {
    method,
    headers: requestHeaders,
    body,
    credentials: 'include'  // Include cookies for session management
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API request failed: ${response.status} ${errorText}`);
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    return null as T;
  }

  return response.json();
}

/**
 * Convenience methods for common HTTP verbs
 */
export const api = {
  get: <T = any>(endpoint: string, headers?: Record<string, string>) => 
    apiRequest<T>(endpoint, { method: 'GET', headers }),
    
  post: <T = any>(endpoint: string, data?: any, headers?: Record<string, string>) => 
    apiRequest<T>(endpoint, { 
      method: 'POST', 
      body: data ? JSON.stringify(data) : undefined,
      headers 
    }),
    
  put: <T = any>(endpoint: string, data?: any, headers?: Record<string, string>) => 
    apiRequest<T>(endpoint, { 
      method: 'PUT', 
      body: data ? JSON.stringify(data) : undefined,
      headers 
    }),
    
  patch: <T = any>(endpoint: string, data?: any, headers?: Record<string, string>) => 
    apiRequest<T>(endpoint, { 
      method: 'PATCH', 
      body: data ? JSON.stringify(data) : undefined,
      headers 
    }),
    
  delete: <T = any>(endpoint: string, headers?: Record<string, string>) => 
    apiRequest<T>(endpoint, { method: 'DELETE', headers })
};

export default api;