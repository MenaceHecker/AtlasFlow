provider "aws" {
  region                      = var.region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
  s3         = "http://127.0.0.1:4566"
  sqs        = "http://127.0.0.1:4566"
  sns        = "http://127.0.0.1:4566"
  dynamodb   = "http://127.0.0.1:4566"
  iam        = "http://127.0.0.1:4566"
  lambda     = "http://127.0.0.1:4566"
  sts        = "http://127.0.0.1:4566"
  cloudwatch = "http://127.0.0.1:4566"
  logs       = "http://127.0.0.1:4566"
  ssm        = "http://127.0.0.1:4566"
}
}

provider "random" {}
