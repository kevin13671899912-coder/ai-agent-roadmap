START
  ↓
query_employee
  ↓
employee exists?
  ├── no → employee_not_found → END
  └── yes → check_permission
                 ↓
            permission?
              ├── no → permission_denied → END
              └── yes → query_leader → END