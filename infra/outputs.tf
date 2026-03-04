output "s3_payload_bucket" {
  value = aws_s3_bucket.payloads.bucket
}

output "sqs_events_queue_url" {
  value = aws_sqs_queue.events.url
}

output "sqs_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

