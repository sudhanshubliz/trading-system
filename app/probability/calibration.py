from __future__ import annotations

from app.probability.types import CalibrationBucket


def calibration_bucket_report(
    predictions: list[float],
    outcomes: list[int | bool],
    *,
    bucket_count: int = 10,
) -> list[CalibrationBucket]:
    bucket_count = max(1, bucket_count)
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bucket_count)]
    for prediction, outcome in zip(predictions, outcomes, strict=False):
        clipped_prediction = max(0.0, min(1.0, float(prediction)))
        bucket_index = min(bucket_count - 1, int(clipped_prediction * bucket_count))
        buckets[bucket_index].append((clipped_prediction, 1.0 if bool(outcome) else 0.0))

    report: list[CalibrationBucket] = []
    for index, bucket in enumerate(buckets):
        lower_bound = index / bucket_count
        upper_bound = (index + 1) / bucket_count
        if bucket:
            mean_prediction = sum(item[0] for item in bucket) / len(bucket)
            observed_frequency = sum(item[1] for item in bucket) / len(bucket)
        else:
            mean_prediction = (lower_bound + upper_bound) / 2.0
            observed_frequency = 0.0
        report.append(
            CalibrationBucket(
                bucket_label=f"{lower_bound:.1f}-{upper_bound:.1f}",
                lower_bound=round(lower_bound, 6),
                upper_bound=round(upper_bound, 6),
                sample_count=len(bucket),
                mean_prediction=round(mean_prediction, 6),
                observed_frequency=round(observed_frequency, 6),
            )
        )
    return report
