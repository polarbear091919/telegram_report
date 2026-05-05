"""Tests for main.parse_args and main.compute_exit_code (pure functions only).

The full main() is exercised by Task 11's smoke test (real Telegram + Supabase).
"""
from __future__ import annotations

import pytest

from main import compute_exit_code, parse_args
from collector import RunResult


# === parse_args ===

def test_parse_args_no_flags_defaults():
    args = parse_args([])
    assert args.cutoff_days is None
    assert args.dry_run is False
    assert args.verbose is False


def test_parse_args_cutoff_days():
    args = parse_args(['--cutoff-days', '7'])
    assert args.cutoff_days == 7


def test_parse_args_dry_run():
    args = parse_args(['--dry-run'])
    assert args.dry_run is True


def test_parse_args_verbose_short():
    args = parse_args(['-v'])
    assert args.verbose is True


def test_parse_args_verbose_long():
    args = parse_args(['--verbose'])
    assert args.verbose is True


# === compute_exit_code ===

def test_exit_code_success_with_zero_failures():
    assert compute_exit_code(RunResult(processed=5)) == 0


def test_exit_code_success_with_no_messages():
    assert compute_exit_code(RunResult()) == 0


def test_exit_code_partial_failure_in_stage_b():
    assert compute_exit_code(RunResult(processed=3, failed=1)) == 2


def test_exit_code_partial_failure_in_stage_a():
    assert compute_exit_code(RunResult(retried_fail=1)) == 2


def test_exit_code_partial_failure_both_stages():
    assert compute_exit_code(RunResult(processed=2, failed=1, retried_fail=1)) == 2
