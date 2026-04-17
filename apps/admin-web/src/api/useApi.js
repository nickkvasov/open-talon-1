import axios from 'axios';
import { useAuth } from 'react-oidc-context';
import { useMemo } from 'react';
import { runtimeConfig } from '../config/runtime';

export function useApi() {
  const auth = useAuth();

  const api = useMemo(() => {
    const instance = axios.create({
      baseURL: runtimeConfig.gatewayUrl,
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
