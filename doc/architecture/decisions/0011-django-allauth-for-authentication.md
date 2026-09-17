# 11. Adopt django-allauth for Wagtail admin authentication

**Date**: 2026-09-17

## Status

Accepted

## Context

### Current Authentication Scope

The application itself does not have a user-facing login. Authentication is currently only required for the **Wagtail admin interface**.

Wagtail's built-in authentication is currently used to authenticate users who access the admin. Authorization is handled separately through Wagtail's groups and permissions.

We have different groups of users, including internal editors and groups for external users (dashboard researcher groups). The access each group has within the Wagtail admin is controlled by Wagtail's existing group permissions. This provides the RBAC/authorization model for the application.

The current setup therefore has two distinct concerns:

- **Authentication** – establishing the identity of a user who wants to access the Wagtail admin.
- **Authorization / RBAC** – determining what an authenticated user is allowed to access or change within Wagtail, based on Wagtail groups and permissions.

This ADR concerns **authentication only**, the existing Wagtail groups, permissions, or RBAC model will continue.

### Problem

Our primary goal is to support modern authentication best practices for users accessing the Wagtail admin, starting with Multi-Factor Authentication (MFA).

Django and Wagtail provide built-in authentication, but the current authentication setup does not provide the additional capabilities we want to support, such as:

- Multi-Factor Authentication (MFA)
- Passkeys / WebAuthn
- Authentication through external identity providers using OIDC
- Potential organisation-level single sign-on

We could implement these capabilities ourselves on top of the existing Django/Wagtail authentication. However, this would require us to develop and maintain security-sensitive authentication functionality and potentially implement additional authentication mechanisms as our requirements evolve. We therefore evaluated existing Django/Wagtail authentication packages that could provide a suitable foundation.

The following packages were considered:

- **`wagtail-2fa`** – Provides two-factor authentication specifically for Wagtail and builds on `django-otp`. It addresses the immediate TOTP-based MFA requirement, but has a narrower scope than the authentication foundation we are looking for.

- **`django-otp`** – Provides OTP functionality and can be used as a building block for MFA. Using it directly would still require us to design and maintain more of the authentication flow and its integration with Wagtail.

- **`django-two-factor-auth`** – Provides a more complete two-factor authentication flow on top of `django-otp`. It addresses MFA well, but is primarily focused on two-factor authentication rather than providing the broader authentication capabilities we may need later.

- **`django-allauth`** – Provides a broader authentication framework with support for MFA and a path toward passkeys and OIDC. It allows us to establish a dedicated authentication layer for Wagtail while keeping the existing Wagtail authorization model unchanged.

## Decision

We will use **`django-allauth` as the authentication framework for the Wagtail admin**.

The immediate goal is to move authentication for Wagtail admin users from the existing Django/Wagtail authentication flow to `django-allauth`, establishing it as the foundation for authentication-related functionality. MFA will be implemented on top of this foundation as the next concrete authentication capability.

`django-allauth` will only be responsible for **authentication**. It will not replace or manage our existing Wagtail authorization/RBAC model.

In particular:

- Wagtail groups will continue to represent the different categories of users, such as internal editors and external users.
- Wagtail group permissions will continue to determine what authenticated users can access and modify.
- The existing Wagtail permission model is not being replaced with an `allauth`-based authorization model.

Passkeys and OIDC are **not part of the current implementation commitment**. They are potential future extensions that can be evaluated and implemented if they become requirements.

If OIDC is introduced later, the expected direction is to integrate with an organisation-level identity provider such as DC's Keycloak and/or LS Sign In.

## Implementation Plan

The implementation will be incremental, with the initial phases focused on establishing the new authentication foundation and adding MFA.

### Phase 1 – Adopt `django-allauth`

Switch authentication for the Wagtail admin to `django-allauth`. The existing Wagtail groups, users, and permissions should continue to provide the authorization/RBAC model.

The goal of this phase is to change the authentication mechanism without changing which users have access to which parts of the Wagtail admin.

### Phase 2 – Implement MFA

Add MFA for Wagtail admin users using `django-allauth`. This phase will cover the required MFA enrolment, authentication, recovery, and user experience flows.

The existing Wagtail permissions remain unchanged.

### Potential Phase 3 – Passkeys

If passkeys become a requirement, evaluate and implement passkey/WebAuthn authentication using the `django-allauth` authentication foundation.

The exact authentication methods and user experience would be defined as part of this phase.

### Potential Phase 4 – OIDC / Organisation Identity Provider

If organisation-level single sign-on becomes a requirement, evaluate OIDC integration with an external identity provider.

Potential providers include our organisation's **Keycloak and/or LS Sign In**, depending on the identity architecture and requirements at that time.

This phase would allow authentication for Wagtail admin users to be delegated to an organisation-level identity provider rather than relying solely on local application authentication.

The existing Wagtail groups and permissions would continue to control what authenticated users are allowed to do within the admin.

## Consequences

### Positive

- We establish a dedicated authentication framework for Wagtail admin access instead of implementing additional authentication functionality ourselves.
- MFA can be added using an established authentication framework.
- The authentication layer has a potential path toward passkeys and OIDC without committing to those features now.
- Future integration with an organisation-level identity provider can use an established standard such as OIDC.
- Authentication and authorization remain clearly separated.
- The existing Wagtail groups and permissions can continue to provide the application's RBAC model.
- The phased approach allows future authentication capabilities to be introduced when they are actually required.

### Negative

- `django-allauth` introduces an additional dependency and authentication abstraction.
- Integrating `django-allauth` with Wagtail's existing admin authentication and user-management flows will require development and testing.
- We will need to maintain the interaction between `django-allauth`, Django, Wagtail, and the existing Wagtail permission model.
- If OIDC is introduced later, there may be additional considerations around mapping externally authenticated identities to existing Wagtail users and groups.
- Introducing additional authentication methods may require changes to the Wagtail admin user experience.

### Mitigation

- **Additional dependency and abstraction**  
  Keep `django-allauth` isolated to the authentication boundary and avoid coupling application-specific business logic directly to `allauth` internals. This should make future upgrades or replacement of the authentication provider easier.

- **Integration complexity**  
  Introduce `django-allauth` incrementally, with the first phase focused only on Wagtail admin authentication. Keep the existing Wagtail authorization model unchanged and add automated tests around the authentication flow and existing permissions.

- **Interaction with the existing Wagtail permission model**  
  Treat the existing Wagtail user, groups, and permissions as the source of authorization information. `django-allauth` should establish the authenticated identity without introducing a separate RBAC or permission system. User, group, and permission behaviour should be verified as part of the migration.

- **Future identity-provider integration**  
  Keep authentication separate from authorization so that a future OIDC integration can map an externally authenticated identity to a Wagtail user while Wagtail groups and permissions continue to control access.

- **Changes to the user experience**  
  Introduce additional authentication methods incrementally. MFA will be addressed in the next phase, while passkeys and OIDC will only be introduced if they become concrete requirements. Each addition should include appropriate UX evaluation and testing.

### Long-term consideration

This decision establishes `django-allauth` as the authentication foundation for the Wagtail admin without committing the application to every authentication capability it supports.

MFA is the next planned capability. Passkeys and OIDC remain optional future implementations and can be evaluated based on future requirements.

Throughout these changes, **authentication remains separate from authorization**: `django-allauth` establishes who the Wagtail admin user is, while Wagtail groups and permissions continue to determine what that user is allowed to do.
