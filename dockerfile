FROM ubuntu:latest

ENV SLACK_CLIENT_ID="1234567890"
ENV SLACK_CLIENT_SECRET=1234567890abcdef

RUN apt update
RUN apt upgrade -y
RUN apt install git python3-pip -y
RUN pip3 install git+https://github.com/pavooq/snapshotter.git

# Expose port 8080 to the outside world
EXPOSE 8080

# Command to run the executable
CMD ["snapshotter", "auth", "127.0.0.1", "8080"]