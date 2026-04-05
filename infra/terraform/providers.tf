terraform {
  required_version = ">= 1.6.0"

  required_providers {
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 1.8"
    }

		null = {
			source  = "hashicorp/null"
			version = "~> 3.2"
		}
  }
}

provider "fabric" {
}

provider "null" {
}
