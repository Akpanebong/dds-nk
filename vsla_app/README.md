# DDS-NK THRIVE — VSLA Django module

A reusable Django app for Village Savings and Loan Associations (VSLAs), designed to integrate with the DDS-NK THRIVE management system.

## Included
- VSLA group registration and lifecycle/status
- Member registration and membership status
- Weekly savings ledger (deposit/withdrawal entries; posted entries are immutable through the UI)
- Loan application, approval/rejection, disbursement and repayment tracking
- Meetings and attendance
- Social fund ledger
- Dashboard KPIs, recent transactions and Chart.js-ready data
- Django admin registration
- Bootstrap templates extending `module_base.html`
- Uses `settings.AUTH_USER_MODEL`, so staff references resolve to your configured `StaffProfile` model
- Login protection and configurable permission gate

## Install
1. Copy the `vsla` directory into the Django project beside your other apps.
2. Add `"vsla"` to `INSTALLED_APPS`.
3. Add to the project's root `urls.py`:
   ```python
   path("vsla/", include("vsla.urls")),
   ```
4. Run:
   ```bash
   python manage.py makemigrations vsla
   python manage.py migrate
   ```
5. Add the sidebar link using `vsla:dashboard`. The sidebar is at `templates/vsla/_sidebar.html`.
6. Ensure Chart.js and Bootstrap Icons are already available through `module_base.html`; the templates do not bundle third-party libraries.

## Integration notes
- `created_by`, `approved_by`, and other staff fields use `settings.AUTH_USER_MODEL`. With `AUTH_USER_MODEL` set to your `StaffProfile`, this connects to the account model supplied for DDS-NK.
- Project/donor are recorded as reference labels (`project_name`, `donor_name`) rather than guessing the names of your existing Project and Donor models. If your project has canonical models, replace those fields with `ForeignKey` fields to those exact models before the first production migration.
- The app uses its own timestamps and Django model permissions. It does not assume your custom `AuditStampedModel` import path or undocumented `manage_access` structure.
- Default access gate: authenticated staff/superusers, or users with Django permission `vsla.access_vsla`. Adjust `vsla/access.py` to match your DDS-NK permission convention. Grant permission via a group/role or adapt the helper to your `manage_access.vsla` flag.
- Financial records are deliberately soft-controlled: a transaction's group/member consistency is validated; loan decisions and financial posting occur through POST-only views; posted savings/social-fund entries are not edited/deleted from the UI. For a production accounting environment, add a formal reversal workflow and approval separation-of-duties rules.
- Configure currency label in templates as UGX by default; change it if your programme uses another currency.

## Recommended production hardening
- Add an explicit `vsla_access` boolean/role to `StaffProfile` if that fits your permissions model.
- Replace project/donor reference labels with foreign keys to your canonical project/donor models.
- Configure database backups, audit log retention, HTTPS, CSRF, and restricted access to member personal data.
- Add tests around loan approval/disbursement, repayment allocation, and concurrent savings posting before production deployment.
