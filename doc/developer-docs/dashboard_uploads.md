# Dashboard uploads and researcher access

## Developer setup and handoff

Developers create and configure new dashboards before handing them over to
editors and researchers. Editors edit existing dashboards; they do not set up
new ones. The developer setup steps are:

1. Create and configure the Wagtail dashboard page.
2. Register its visualization service in `dashboard_visualisation.registry` and
   verify its accepted file format.
3. Create the **Dashboard data upload** snippet with a meaningful dashboard title,
   the matching page slug, its research group, and an initial valid source file.
   The upload title is maintained separately from the page title.
4. Give the research group Wagtail admin access and **change dashboard data upload**
   permission. Add the researchers to that group.
5. Confirm that the upload appears for a researcher and that the initial figures
   display correctly on the public dashboard.

Research groups and permissions are managed through Wagtail; application startup
does not seed or change these assignments. Before rolling out access changes,
review group grants and confirm that assigned uploads have completed this setup.

Superusers and members of the `Editors` group count as internal users in the
permission checks; editors still need the corresponding Django model permissions.
This technical classification does not assign dashboard setup to editors.

## Researcher workflow

Researchers see only uploads assigned to one of their groups. The listing shows
the dashboard title and data-updated date, both read-only. Opening an upload shows
its read-only title and the source-file control. Researchers replace the file and
click **Save** to update their dashboard immediately.

Researchers cannot create pages or upload rows through this workflow. Creation,
copying, deletion (including bulk deletion), history, revision comparison and
restoration, usage, and snippet chooser screens are reserved for internal users.
Granting additional dashboard add/delete permissions does not override the
researcher restrictions. Membership in `Editors` does override them, so do not
add researcher-only accounts to that group.

The dashboard slug, research group, generated figure JSON, date override, file
hash, and uploader attribution cannot be edited by researchers. The server ignores
forged form values for those fields, and the title is also protected. Public page
URLs, charts, and source-file downloads continue to work normally.

## Save behavior and troubleshooting

- Validation uses the stored dashboard slug to select the correct file validator.
  Invalid files do not change the upload or create a revision.
- A changed file regenerates the figures and sets the data-updated date to today.
  The uploader is recorded from the authenticated user.
- Re-uploading identical file contents preserves the figures and date and shows
  a warning. The uploader is still recorded.
- If generation fails, the new source file remains saved while the previous
  figures and date are retained. Researchers are directed to an editor; internal
  feedback and application logs retain the diagnostic details.
- If generation returns no figures, the saved figures become empty and the date
  updates, following the existing save behavior. Researchers receive an instruction
  to ask an editor to check the dashboard configuration.
- Normal saves continue to record Wagtail revisions for internal audit and
  restoration. Autosave is disabled, and researchers cannot overwrite revisions.

An upload with no assigned research group is available to internal users only.
