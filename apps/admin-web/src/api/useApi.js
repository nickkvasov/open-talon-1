import axios from 'axios';
import { useAuth } from 'react-oidc-context';
import { useMemo } from 'react';

const GATEWAY_URL = 'http://localhost:8000';

export function useApi() {
  const auth = useAuth();

  const api = useMemo(() => {
    const instance = axios.create({
      baseURL: GATEWAY_URL,
    });

    instance.interceptors.request.use((config) => {
      if (auth.user?.access_token) {
        config.headers.Authorization = `Bearer ${auth.user.access_token}`;
      }
      return config;
    });

    return instance;
  }, [auth.user?.access_token]);

  return api;
}
