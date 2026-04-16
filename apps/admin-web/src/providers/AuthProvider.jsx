import React from 'react';
import { AuthProvider as OidcProvider } from 'react-oidc-context';

const oidcConfig = {
  authority: 'http://localhost:8081/realms/open-talon',
  client_id: 'open-talon-admin-web', 
  redirect_uri: window.location.origin,
  response_type: 'code',
  scope: 'openid profile email roles',
  post_logout_redirect_uri: window.location.origin,
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
