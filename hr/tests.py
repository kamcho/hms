from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from hr.leave_utils import get_leave_entitlement, leave_balance_snapshot, validate_leave_balance
from hr.models import LeaveRequest, LeaveType, StaffLeaveEntitlement

User = get_user_model()


class LeaveBalanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            id_number='STF001',
            password='test-pass',
            first_name='Alice',
            last_name='Worker',
            role='Nurse',
        )
        self.leave_type = LeaveType.objects.create(name='Annual', days_per_year=5)

    def _create_leave(self, *, start, end, status='Approved'):
        return LeaveRequest.objects.create(
            user=self.user,
            leave_type=self.leave_type,
            start_date=start,
            end_date=end,
            status=status,
        )

    def test_remaining_days_after_approved_leave(self):
        self._create_leave(start=date(2026, 1, 2), end=date(2026, 1, 4))

        snapshot = leave_balance_snapshot(self.user, self.leave_type, 2026)

        self.assertEqual(snapshot['entitlement'], 5)
        self.assertEqual(snapshot['used'], 3)
        self.assertEqual(snapshot['remaining'], 2)

    def test_pending_leave_counts_against_balance(self):
        self._create_leave(start=date(2026, 2, 1), end=date(2026, 2, 3), status='Pending')

        snapshot = leave_balance_snapshot(self.user, self.leave_type, 2026)

        self.assertEqual(snapshot['pending'], 3)
        self.assertEqual(snapshot['remaining'], 2)

    def test_validate_leave_balance_blocks_over_limit(self):
        self._create_leave(start=date(2026, 3, 1), end=date(2026, 3, 4))

        errors = validate_leave_balance(
            self.user,
            self.leave_type,
            date(2026, 4, 1),
            date(2026, 4, 2),
        )

        self.assertEqual(len(errors), 1)
        self.assertIn('only 1 remain', errors[0])

    def test_validate_leave_balance_allows_within_limit(self):
        self._create_leave(start=date(2026, 5, 1), end=date(2026, 5, 2))

        errors = validate_leave_balance(
            self.user,
            self.leave_type,
            date(2026, 6, 1),
            date(2026, 6, 2),
        )

        self.assertEqual(errors, [])

    def test_staff_entitlement_override(self):
        StaffLeaveEntitlement.objects.create(
            user=self.user,
            leave_type=self.leave_type,
            days_per_year=10,
        )

        snapshot = leave_balance_snapshot(self.user, self.leave_type, 2026)

        self.assertEqual(snapshot['entitlement'], 10)
        self.assertEqual(get_leave_entitlement(self.user, self.leave_type), 10)
