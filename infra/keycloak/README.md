# Keycloak for single sign-on tests (phase 6, D62)

Two realms stand for two organizations' identity providers: `vtc` and `safety`, each with a confidential client
`harak2`. Everything here is a **test fixture** for a throwaway local Keycloak: the client secrets and the user
password (`harak-sso-test`) protect nothing and must never be used anywhere else.

| realm | users | for |
|---|---|---|
| vtc | noura@vtc.test, hamed@vtc.test | first sign-in, enforcement |
| vtc | ghost@vtc.test (email not verified) | refused |
| vtc | outsider@elsewhere.test (domain not verified) | refused |
| safety | faisal@safety.test | a second organization |

Run it:

- with Docker (CI, compose): `docker compose -f infra/docker-compose.yml --profile sso-test up keycloak`
- without Docker (the cloud dev container): `infra/keycloak/run-local.sh`, which runs the same version from the
  Maven Central distribution on Java 21.

Either way it listens on http://localhost:8180, and the issuer of a realm is `http://localhost:8180/realms/<realm>`.
