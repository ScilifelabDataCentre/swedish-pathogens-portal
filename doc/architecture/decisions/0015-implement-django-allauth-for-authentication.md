# 15. Implement django-allauth for authentication (Phase 1)

**Date**: 2026-11-06

## Status

Accepted

## Context

As described in [ADR 0011 – Adopt django-allauth for Wagtail admin authentication](https://github.com/ScilifelabDataCentre/swedish-pathogens-portal/blob/main/doc/architecture/decisions/0011-django-allauth-for-authentication.md), we have decided to adopt `django-allauth` as the authentication framework. The adoption is planned in phases and this ADR defines the implementation details and boundaries for Phase 1.

The main goal of this phase is to move the authentication flow from Wagtail's built-in login mechanism to `django-allauth`, without changing how users, groups, and permissions are managed within the application.

There are a few areas where we need to establish clear boundaries between the responsibilities of `django-allauth` and Wagtail:

- **Authentication** – handled by `django-allauth`, including login, email and password management, and logout.
- **User and group management** – continues to be handled by Wagtail.
- **Authorisation / RBAC** – continues to rely on Wagtail's existing groups and permissions.

We also want to avoid introducing a separate user registration flow. User accounts should continue to be created and managed by administrators through the Wagtail admin, rather than allowing users to sign themselves up.

## Decision

We will integrate `django-allauth` into the project and make it the sole entry point for authentication and email/password management related operations in the Wagtail admin.

The implementation will follow these decisions:

### Login and authentication

- When an unauthenticated user tries to access the Wagtail admin, they will be redirected to the `django-allauth` login page.
- Direct access to Wagtail's built-in login page will also redirect users to the `django-allauth` login page. We should not have two separate login entry points.
- Users can authenticate using either their username or email address, together with their password.
- Login and authentication-related flows will be handled through `django-allauth`'s URLs and views.

### Email management

- Email address management will primarily be handled by `django-allauth`.
- As an exception, administrators and superusers will provide an initial email address when creating a user through Wagtail.
- Once an account has been created, users should manage their own email addresses through `django-allauth`'s account management functionality.
- Administrators and superusers may still modify a user's email address through Wagtail when necessary, but this should generally be avoided. Changes should preferably be made by the user through `django-allauth` to ensure that the associated email verification flow is respected.

### Password management

- Password management will be handled entirely by `django-allauth`.
- Wagtail's built-in password-related functionality will be disabled to avoid having multiple places for managing passwords.
- When an administrator creates a new user through Wagtail, they will not be able to set an initial password.
- After the account has been created, the user will need to use the `django-allauth` password reset flow to set their own password.
- Password reset and password change operations will be handled through `django-allauth`'s URLs.

### User and group management

- User creation and management will continue to be handled through Wagtail.
- Group creation and management will also remain within Wagtail.
- All user and group-related RBAC operations, including assigning users to groups and managing permissions, will continue to use Wagtail's existing functionality.
- `django-allauth` will not be responsible for creating users, managing groups, assigning permissions, or introducing any additional RBAC functionality.
- Wagtail-related user profile information will continue to be managed through Wagtail.

### Logout

- Logout will be handled by `django-allauth`.
- Wagtail's built-in logout functionality will be redirected to the corresponding `django-allauth` logout flow.

### User registration

- Public user signup will not be enabled.
- Users cannot create their own accounts through a registration page.
- All user accounts must be created by an administrator through the Wagtail admin.

In summary, `django-allauth` will own the authentication lifecycle (login, email/password management, and logout), while Wagtail will remain the place for administrators to manage users, groups, profiles, and permissions.

This phase is intentionally limited to regular credential-based authentication. MFA, passkeys, and OIDC are outside the scope of this ADR and will be addressed in subsequent phases.

## Consequences

### Positive

- We establish a clear separation of responsibilities between authentication and user/permission management.
- All authentication-related operations are handled through a single framework, avoiding conflicts between Wagtail's built-in authentication views and `django-allauth`.
- Supporting both username and email-based login provides users with some flexibility when signing in.
- Administrators can continue using the familiar Wagtail interface for user and group management.
- Users are responsible for setting their own passwords through the password reset flow, rather than having administrators assign or communicate initial passwords.
- Disabling public signup ensures that user account creation remains controlled by administrators.
- This provides the authentication foundation needed for the next phase, where MFA will be introduced without having to revisit the overall authentication architecture.

### Negative

- Authentication-related user information, such as email addresses and passwords, is managed through `django-allauth`, while other user information, groups, and permissions remain managed through Wagtail. This separation may be slightly confusing for administrators.
- The integration requires customisation of Wagtail's built-in authentication and user management interfaces to avoid exposing functionality that is now handled by `django-allauth`.
- Redirecting Wagtail's built-in login and logout flows to `django-allauth` introduces additional integration complexity.
- Newly created users cannot log in immediately after account creation. They must first complete the password setup process through the password reset flow.
- The initial account setup experience depends on the password reset flow and its associated email delivery being properly configured.

### Mitigation

- **Separation of responsibilities**

  Clearly document which system is responsible for each aspect of user management. Keep `django-allauth` focused on authentication-related functionality, including login, email address management, password management, and logout. Wagtail remains responsible for user creation, user profiles, groups, and permissions.

- **Email management**

  Make it clear to administrators that the initial email address must be provided when creating a user through Wagtail, but subsequent email address changes should preferably be made by the user through `django-allauth`. Avoid exposing email editing functionality in Wagtail beyond what is needed for user creation, where possible.

- **Wagtail authentication integration**

  Ensure that all entry points to the Wagtail admin use the `django-allauth` authentication flow. Add appropriate redirects so that users cannot bypass the intended login flow by accessing Wagtail's built-in login URL directly.

- **Password management**

  Disable or hide Wagtail's built-in password management functionality and ensure that password-related operations are only available through `django-allauth`. Test the password reset and password change flows as part of the implementation.

- **New user onboarding**

  Make sure administrators understand that newly created users will not have an initial password. Document that users must use the password reset flow to set their own password. Verify that password reset emails are correctly configured and delivered.

- **User and permission management**

  Keep Wagtail as the source of truth for users, groups, and permissions. Verify that existing users, group memberships, and permissions continue to behave as expected after introducing `django-allauth`.
