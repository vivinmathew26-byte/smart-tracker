#vpc 
resources "aws_vpc" "main_vpc" {
    cidr_block = "10.0.0.0/16"

    tag = {
        Name = "main-vpc"
    }
} 

#subnet
resources "aws_public_subnet" "public_subnet" {
    vpc_id = aws_vpc.main_vpc.vpc_id
    cidr_block = "10.0.1.0/24"
    map_public_ip_on_lanuch = true

    tag = {
        Name = "public-subnet"
    }
}

# internet gateway
resources "aws_internet_gateway" "igw" {
    vpc_id = aws_vpc.main_vpc.id

    tag = {
        Name = "main-igw"
    }
}

#route table
resources "aws_route_table" "public_rt" {
    vpc_id = aws_vpc.main_vpc.id

    route {
        cidr_block = "0.0.0.0/0
        gateway_id = aws_internet_gateway.igw.id
    }
}

#route table association 
resources "aws_route_table_association" "public_assoc" {
    subnet_id = aws_public_subnet.public_subnet.id
    route_table_id = aws_route_table.public_rt.id
}

# Security Group
resource "aws_security_group" "web_sg" {
  name   = "web-sg"
  vpc_id = aws_vpc.main_vpc.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# EC2 Instance
resource "aws_instance" "web_server" {
  ami                    = "ami-0f58b397bc5c1f2e8" # Ubuntu 22.04 (Mumbai)
  instance_type          = "t2.micro"
  subnet_id              = aws_subnet.public_subnet.id
  vpc_security_group_ids = [aws_security_group.web_sg.id]

  key_name = "aws-login"

  tags = {
    Name = "Terraform-EC2"
  }
}