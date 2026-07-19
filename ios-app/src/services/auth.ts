import apiClient from './api';
import { AuthResponse, User } from '../types/api';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface SignupData {
  email: string;
  password: string;
  full_name?: string;
}

class AuthService {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>('/auth/login', {
      email: credentials.email,
      password: credentials.password,
    });

    // Store token
    await apiClient.setAuthToken(response.access_token);

    return response;
  }

  async signup(data: SignupData): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>('/auth/signup', data);

    // Store token
    await apiClient.setAuthToken(response.access_token);

    return response;
  }

  async logout(): Promise<void> {
    await apiClient.clearAuthToken();
  }

  async getCurrentUser(): Promise<User> {
    return await apiClient.get<User>('/auth/me');
  }

  async isAuthenticated(): Promise<boolean> {
    const token = await apiClient.getAuthToken();
    if (!token) return false;

    try {
      await this.getCurrentUser();
      return true;
    } catch {
      return false;
    }
  }
}

export const authService = new AuthService();
export default authService;
