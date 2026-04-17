function normalizeBasePath(value) {
  if (!value || value === '/') {
    return '/';
  }

  const withLeadingSlash = value.startsWith('/') ? value : `/${value}`;
  return withLeadingSlash.replace(/\/+$/, '');
}

async function loadFileConfig() {
  try {
    const response = await fetch(new URL(/* @vite-ignore */ '../runtime-config.json', import.meta.url), {
      cache: 'no-store',
    });
    if (!response.ok) {
      return {};
    }
    const config = await response.json();
    return typeof config === 'object' && config !== null ? config : {};
  } catch {
    return {};
  }
}

const fileConfig = await loadFileConfig();

const gatewayUrl = (
  fileConfig.gatewayUrl
  || import.meta.env.VITE_GATEWAY_URL
  || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');
const keycloakBaseUrl = (
  fileConfig.keycloakBaseUrl
  || import.meta.env.VITE_KEYCLOAK_BASE_URL
  || 'http://127.0.0.1:8081'
).replace(/\/+$/, '');
const keycloakRealm = fileConfig.keycloakRealm || import.meta.env.VITE_KEYCLOAK_REALM || 'open-talon';
const oidcClientId = fileConfig.oidcClientId || import.meta.env.VITE_OIDC_CLIENT_ID || 'open-talon-web';
const appBasePath = normalizeBasePath(
  fileConfig.appBasePath || import.meta.env.VITE_APP_BASE_PATH || '/'
);
const appBaseUrl = new URL(appBasePath === '/' ? '/' : `${appBasePath}/`, window.location.origin).toString();

export const runtimeConfig = {
  gatewayUrl,
  keycloakBaseUrl,
  keycloakRealm,
  oidcClientId,
  appBasePath,
  appBaseUrl,
  keycloakAuthority: `${keycloakBaseUrl}/realms/${keycloakRealm}`,
};
