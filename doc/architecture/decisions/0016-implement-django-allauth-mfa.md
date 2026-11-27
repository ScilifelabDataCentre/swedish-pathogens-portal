# 16. Implement django-allauth Multi-Factor Authentication (Phase 2)

**Date**: 2026-11-27

## Status

Accepted

## Context

As described in [ADR 0011 – Adopt django-allauth for Wagtail admin authentication](0011-django-allauth-for-authentication.md), we decided to adopt `django-allauth` as the authentication framework for the Wagtail admin, with the implementation planned in multiple phases.

Phase 1, documented in [ADR 0015 – Implement django-allauth for authentication](0015-implement-django-allauth-for-authentication.md), has been implemented. This established `django-allauth` as the authentication entry point for the Wagtail admin, covering username/email and password-based login, email management, password management, and logout. Wagtail continues to be responsible for user, group, and permission management.

The next planned phase is to introduce Multi-Factor Authentication (MFA) to strengthen account security.

For this phase, we will use _Time-based One-Time Password (TOTP)_ as the MFA method. Users will configure an authenticator application (e.g. Google Authenticator, Microsoft Authenticator, or another compatible application) to generate one-time passwords during authentication.

There are a few implementation-specific requirements that need to be addressed:

- **Protection of MFA-related data:** MFA-related data, particularly TOTP secrets, must be encrypted before being stored in the database. This is important because these secrets could otherwise be used to generate valid authentication codes if the database were compromised.
- **Mandatory MFA:** MFA is mandatory for all users accessing the Wagtail admin. However, `django-allauth` does not provide a built-in mechanism to enforce MFA enrolment for all users. Therefore, we need an application-level mechanism to ensure that users cannot access the admin until they have configured MFA.
- **MFA recovery:** Users may lose access to their authenticator application. We need to provide recovery mechanisms, including recovery codes and the ability to deactivate their existing MFA configuration so that they can set up a new one when necessary.
- **Secure MFA management:** Sensitive MFA management operations should require users to re-authenticate to reduce the risk of unauthorized changes, particularly when an authenticated session is compromised.

## Decision

We will extend the existing `django-allauth` implementation from Phase 1 to enable and enforce TOTP-based MFA for all users accessing the Wagtail admin.

The implementation will follow these decisions:

### MFA implementation

- We will use the MFA functionality provided by `django-allauth`, specifically TOTP-based authentication.
- All users accessing the Wagtail admin must configure and activate MFA.
- Once MFA is configured, users will be required to provide a valid TOTP code as part of the authentication process.
- The existing authentication and authorization responsibilities remain unchanged:
  - `django-allauth` continues to handle authentication, including MFA.
  - Wagtail continues to handle user and group management, as well as authorization through its existing groups and permissions.

### Encryption of MFA-related data

- All MFA-related sensitive data, particularly TOTP secrets, must be encrypted before being persisted in the database.
- We will implement a custom `django-allauth` adapter to handle encryption and decryption of MFA-related data.
- Encryption and decryption will be implemented using the `cryptography` Python package, specifically its `Fernet` symmetric authenticated encryption mechanism.
- The adapter will use `MultiFernet`, this allows multiple encryption keys to be configured and makes future key rotation (if needed) easier to manage.
- Encryption will happen before sensitive data is saved to the database, and decryption will happen when the data is retrieved for use by `django-allauth`.

The encryption keys must be managed separately from the database and must not be stored alongside the encrypted MFA data. Access to these keys must be restricted to the application environment.

A secrets management solution, such as **Bitwarden Secrets Manager**, can be used to securely store, manage, and provide encryption keys to the application. The keys should be made available to the application through a secure deployment mechanism rather than being hardcoded or committed to version control.

### Enforcing mandatory MFA

Since `django-allauth` does not provide a built-in mechanism to enforce MFA enrolment for all users, we will implement a custom Django middleware to enforce this requirement.

The middleware will follow these rules:

- A custom Django setting, `MFA_ENFORCE` (boolean), will control whether mandatory MFA enforcement is enabled.
- When `MFA_ENFORCE` is set to `True`, authenticated users who have not yet activated MFA will be redirected to the MFA settings/enrolment page.
- While MFA is not activated, users will not be allowed to access other pages. Requests to other pages will be redirected to the MFA settings page until the user completes MFA setup.
- The middleware must allow access to the necessary MFA-related URLs and static resources to ensure that users can complete the enrolment process without redirect loops.
- When `MFA_ENFORCE` is set to `False`, the middleware will not enforce MFA enrolment. This provides flexibility for development, testing, and other environments where mandatory enforcement may not be required.

This middleware ensures that MFA enrolment is enforced at the application level, independently of the individual views or URLs being accessed.

### Re-authentication for MFA management

- We will set `MFA_REAUTHENTICATION_REQUIRED = True` in the `django-allauth` configuration.
- This requires users to re-authenticate before performing sensitive MFA-related management operations.
- This provides an additional security layer against unauthorized changes to MFA configurations, particularly in cases where an authenticated user session has been compromised.

### Recovery codes

- We will use the recovery code functionality provided by `django-allauth` as an additional recovery mechanism for users who cannot access their authenticator application.
- Users can view, download, and regenerate their recovery codes through the recovery code management endpoints provided by `django-allauth`.
- Recovery codes provide an alternative way to complete MFA verification when a user cannot access their authenticator application.
- Users should be encouraged to download and store their recovery codes securely when configuring MFA.
- Regenerating recovery codes will replace the existing set, meaning previously generated codes will no longer be valid.

We will rely on `django-allauth`'s existing recovery code management functionality rather than implementing a custom recovery code mechanism.

### MFA deactivation and recovery

- The MFA deactivation functionality provided by `django-allauth` will remain available and will not be disabled.
- This is intentional, as users may lose access to their authenticator application and need to remove their existing MFA configuration before registering a new authenticator.
- MFA deactivation will remain protected by the re-authentication requirement configured through `MFA_REAUTHENTICATION_REQUIRED = True`.

If a user loses access to both their authenticator application and their recovery codes, they will no longer be able to complete MFA verification themselves.

In such cases:

- An administrator must manually remove the user's MFA-related information from the database to restore access.
- After the existing MFA configuration has been removed, the user can sign in using their regular credentials and register a new authenticator.
- This administrator-assisted recovery procedure is an exceptional measure and should only be performed after verifying the user's identity.

We will not implement a separate self-service recovery mechanism for users who have lost access to both their authenticator application and recovery codes.

## Consequences

### Positive

- All users accessing the Wagtail admin will be required to use an additional authentication factor, improving the overall security of user accounts.
- TOTP-based MFA provides an additional layer of protection even if a user's password is compromised.
- Using `django-allauth`'s existing MFA functionality avoids implementing and maintaining a custom MFA authentication flow.
- Encrypting MFA-related sensitive data before database persistence reduces the risk of exposing usable TOTP secrets in the event of a database compromise.
- Using Fernet provides authenticated symmetric encryption, protecting the confidentiality and integrity of the encrypted data.
- Using `MultiFernet` provides a straightforward path for encryption key rotation without requiring a change to the overall encryption implementation.
- Using a dedicated secrets management solution, such as Bitwarden Secrets Manager, provides a centralized and secure way to manage application encryption keys.
- The custom middleware provides a centralized mechanism for enforcing mandatory MFA across the application rather than relying on individual views to enforce it.
- The `MFA_ENFORCE` setting provides flexibility to enable or disable mandatory MFA enforcement depending on the environment.
- Requiring re-authentication for MFA management operations adds an additional layer of protection against unauthorized changes to MFA configurations.
- Recovery codes provide users with an alternative way to authenticate when they lose access to their authenticator application.
- The ability to view, download, and regenerate recovery codes through `django-allauth` avoids implementing and maintaining a custom recovery code management mechanism.
- Keeping MFA deactivation available provides users with a recovery path if they lose access to their authenticator application.
- Administrator-assisted recovery provides a fallback mechanism for users who lose access to both their authenticator application and recovery codes.
- The implementation builds on the authentication foundation established in Phase 1 without changing the existing Wagtail user, group, and permission model.

### Negative

- Introducing MFA adds an additional step to the authentication process, which may slightly increase the time and effort required for users to sign in.
- Users must have access to a compatible authenticator application and keep it available when signing in.
- The custom adapter introduces additional complexity because MFA-related data must be correctly encrypted and decrypted throughout the persistence lifecycle.
- Encryption key management becomes an additional operational responsibility. Losing the encryption keys could make existing MFA secrets impossible to decrypt, potentially preventing affected users from authenticating with MFA.
- The custom middleware introduces additional complexity in the request lifecycle and must correctly handle authentication status, MFA enrolment status, and allowed URLs to avoid redirect loops or unintended access restrictions.
- Leaving MFA deactivation available introduces a potential security consideration, as users may remove their second authentication factor.
- Recovery codes must be stored securely by users. If an attacker obtains unused recovery codes, they may be able to use them to bypass TOTP verification.
- If `MFA_ENFORCE` is accidentally disabled in a production environment, users who have not configured MFA may still be able to access the application without it.
- Administrator-assisted recovery introduces an operational dependency on administrators and requires manual database intervention when users lose access to both their authenticator application and recovery codes.

### Mitigation

- **MFA usability**

  Provide clear instructions for configuring an authenticator application and completing MFA enrolment. Ensure that the enrolment and authentication flows are tested and documented.

- **Encryption of MFA-related data**

  Ensure that the custom adapter consistently encrypts sensitive MFA data before saving it to the database and decrypts it when required by `django-allauth`. Add automated tests covering encryption, decryption, and persistence to verify that sensitive values are never stored in plaintext.

- **Encryption key management**

  Store encryption keys outside the application database and manage them through environment-specific secrets or an appropriate secrets management solution, such as Bitwarden Secrets Manager. Restrict access to these keys and ensure that they are backed up securely.

  Use `MultiFernet` to support multiple encryption keys. If key rotation is implemented in future, retain previous keys for decryption until all data encrypted with those keys has been re-encrypted or otherwise migrated. Document the key rotation procedure to avoid accidental loss of access to existing MFA configurations.

- **Middleware enforcement**

  Add automated tests to verify that users without activated MFA are redirected to the MFA settings page when `MFA_ENFORCE` is enabled. Ensure that the middleware allows access to the necessary MFA enrolment URLs and static resources and does not introduce redirect loops.

  Also verify that users with activated MFA can access the application normally and that disabling `MFA_ENFORCE` removes the enrolment restriction as expected.

- **Mandatory MFA configuration**

  Ensure that `MFA_ENFORCE` is explicitly enabled in production environments and treat this setting as a security-sensitive configuration.

- **Re-authentication for MFA management**

  Keep `MFA_REAUTHENTICATION_REQUIRED = True` to ensure that users must re-authenticate before performing sensitive MFA-related operations.

  Add automated tests to verify that MFA management operations enforce re-authentication as expected.

- **Recovery codes**

  Encourage users to download their recovery codes during MFA setup and store them in a secure location, such as a password manager.

  Make users aware that recovery codes should be treated as sensitive credentials and must not be shared with others. When recovery codes are regenerated, the previous set should be considered invalid and discarded.

- **MFA deactivation and recovery**

  Keep the MFA deactivation functionality available to support users who lose access to their authenticator application. Ensure that deactivation follows the authentication and security checks provided by `django-allauth`.

  Document the recovery procedure so that users understand how to use recovery codes or deactivate their existing MFA configuration and register a new authenticator when necessary.

  For users who lose access to both their authenticator application and recovery codes, document an administrator-assisted recovery procedure. Administrators must verify the user's identity before manually removing MFA-related information from the database. This procedure should be restricted to authorized administrators and treated as an exceptional recovery operation.

- **Authentication and authorization separation**

  Keep MFA enforcement within the authentication layer and avoid introducing changes to Wagtail's existing authorization model. Wagtail groups and permissions must continue to determine what authenticated users are allowed to access and modify.
