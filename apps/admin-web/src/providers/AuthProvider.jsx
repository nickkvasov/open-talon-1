import React from 'react';
import { AuthProvider as OidcProvider } from 'react-oidc-context';
import { runtimeConfig } from '../config/runtime';

const oidcConfig = {
  authority: runtimeConfig.keycloakAuthority,
  client_id: runtimeConfig.oidcClientId,
  redirect_uri: runtimeConfig.appBaseUrl,
  response_type: 'code',
  scope: 'openid profile email roles',
  post_logout_redirect_uri: runtimeConfig.appBaseUrl,
  onSigninCallback: (_user) => {
    window.history.replaceState(
      {},
      document.title,
      window.location.pathname
    );
  }
};

export const AuthProvider = ({ children }) => {
  return (
    <OidcProvider {...oidcConfig}>
      {children}
    </OidcProvider>
  );
};
