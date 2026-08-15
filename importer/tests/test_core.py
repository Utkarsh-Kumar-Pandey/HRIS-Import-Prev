from io import BytesIO
from unittest import TestCase

from importer.core import UploadError, analyze_upload


HEADER = "employee_id,employee_name,email,manager_id,manager_email,department\n"


def upload(body: str) -> BytesIO:
    return BytesIO((HEADER + body).encode("utf-8"))


class HRISAnalysisTests(TestCase):
    def test_duplicate_identity_rows_are_all_excluded(self):
        result = analyze_upload(
            upload(
                "E1,Alice,alice@example.com,,,Engineering\n"
                "E1,Bob,bob@example.com,,,Sales\n"
                "E3,Carol,ALICE@example.com,,,Finance\n"
            )
        )

        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(
            [(error.row_number, error.message) for error in result.errors],
            [
                (2, "duplicate employee_id: E1"),
                (2, "duplicate email: alice@example.com"),
                (3, "duplicate employee_id: E1"),
                (4, "duplicate email: alice@example.com"),
            ],
        )

    def test_both_manager_references_must_point_to_same_employee(self):
        result = analyze_upload(
            upload(
                "M1,Manager One,m1@example.com,,,Ops\n"
                "M2,Manager Two,m2@example.com,,,Ops\n"
                "E1,Employee,e1@example.com,M1,m2@example.com,Ops\n"
            )
        )

        self.assertEqual(result.accepted_count, 3)
        self.assertIn((4, "manager reference conflict"), [(e.row_number, e.message) for e in result.errors])
        self.assertEqual({employee.employee_id for employee in result.root_employees}, {"M1", "M2"})
        self.assertEqual(result.manager_direct_report_counts, [])

    def test_cycle_detection_marks_cycle_members_but_not_tail(self):
        result = analyze_upload(
            upload(
                "A,Alice,a@example.com,B,,Eng\n"
                "B,Bob,b@example.com,C,,Eng\n"
                "C,Carol,c@example.com,A,,Eng\n"
                "D,Dan,d@example.com,A,,Eng\n"
            )
        )

        self.assertEqual(
            {employee.employee_id for employee in result.cyclic_employees},
            {"A", "B", "C"},
        )
        self.assertNotIn("D", {employee.employee_id for employee in result.cyclic_employees})

    def test_quoted_commas_and_bom_are_supported(self):
        data = (
            "\ufeffemployee_id,employee_name,email,manager_id,manager_email,department\n"
            'E1,"Doe, Jane", JANE@EXAMPLE.COM ,,,"People, Culture"\n'
        ).encode("utf-8")

        result = analyze_upload(BytesIO(data))
        employee = result.accepted_employees[0]
        self.assertEqual(employee.employee_name, "Doe, Jane")
        self.assertEqual(employee.email, "jane@example.com")
        self.assertEqual(employee.department, "People, Culture")

    def test_missing_required_header_is_upload_error(self):
        data = b"employee_id,email\nE1,a@example.com\n"
        with self.assertRaises(UploadError):
            analyze_upload(BytesIO(data))
