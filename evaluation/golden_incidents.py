GOLDEN_INCIDENTS = [
    {
        "id": "INC-001",
        "type": "deploy_regression",
        "title": "High error rate on payment-api",
        "service": "payment-api",
        "description": "Error rate on /charge endpoint spiked to 23% after deploy v2.14.3. "
                       "New payment gateway integration introduced a bug in the charge flow.",
        "expected_verdict": "Deploy-related regression",
        "expected_confidence": 0.85,
        "expected_sources": ["github", "datadog"],
        "scoring": {
            "evidence_coverage": 4,
            "correct_root_cause": True,
            "summary_usefulness": 4,
            "time_to_answer_s": 30,
        },
    },
    {
        "id": "INC-002",
        "type": "deploy_regression_latency",
        "title": "Latency spike on checkout-service",
        "service": "checkout-service",
        "description": "P99 latency on /checkout increased from 200ms to 12s. "
                       "Promotional pricing engine PR #178 touched cart, discount, and checkout flows.",
        "expected_verdict": "Deploy-related regression",
        "expected_confidence": 0.65,
        "expected_sources": ["github", "datadog"],
        "scoring": {
            "evidence_coverage": 4,
            "correct_root_cause": True,
            "summary_usefulness": 4,
            "time_to_answer_s": 30,
        },
    },
    {
        "id": "INC-003",
        "type": "database_capacity",
        "title": "Database connection pool exhaustion on user-db",
        "service": "user-service",
        "description": "Active connections reached 95% of max pool size. "
                       "Recent deploy v1.22.0 added session management with new DB migration.",
        "expected_verdict": "Database capacity pressure",
        "expected_confidence": 0.7,
        "expected_sources": ["datadog", "github"],
        "scoring": {
            "evidence_coverage": 3,
            "correct_root_cause": True,
            "summary_usefulness": 4,
            "time_to_answer_s": 30,
        },
    },
    {
        "id": "INC-004",
        "type": "deploy_failure_canary",
        "title": "Deploy failure on notification-service",
        "service": "notification-service",
        "description": "Canary deployment of new email template engine failed health checks. "
                       "Rolled back automatically.",
        "expected_verdict": "Deploy-related regression",
        "expected_confidence": 0.65,
        "expected_sources": ["github", "datadog"],
        "scoring": {
            "evidence_coverage": 3,
            "correct_root_cause": True,
            "summary_usefulness": 3,
            "time_to_answer_s": 25,
        },
    },
]
