import threading
import time

from sic_framework import (
    SICComponentManager,
    SICConfMessage,
    SICMessage,
    SICRequest,
    utils,
)
from sic_framework.core.component_python2 import SICComponent
from sic_framework.core.connector import SICConnector
from sic_framework.devices.common_naoqi.common_naoqi_motion import NaoqiMotionTools

if utils.PYTHON_VERSION_IS_2:
    import qi
    from naoqi import ALProxy


class StartStreaming(SICRequest):
    def __init__(self, joints):
        """
        Start streaming the positions of the selected joints. For more information see robot documentation:
        For nao: http://doc.aldebaran.com/2-8/family/nao_technical/bodyparts_naov6.html#nao-chains
        For pepper: http://doc.aldebaran.com/2-8/family/pepper_technical/bodyparts_pep.html


        :param joints: One of the robot's "Joint chains" such as ["Body"] or ["LArm", "HeadYaw"]
        :type joints: list[str]
        """
        super(StartStreaming, self).__init__()
        self.joints = joints


class StopStreaming(SICRequest):
    pass

class PepperMotionStream(SICMessage):
    def __init__(self, joints, angles, velocity):
        self.joints = joints
        self.angles = angles
        self.velocity = velocity


class PepperMotionStreamerConf(SICConfMessage):
    def __init__(
        self,
        stiffness=0.6,
        speed=0.75,
        stream_stiffness=0,
        use_sensors=False,
        samples_per_second=20,
    ):
        """
        :param stiffness: Control how much power the robot should use to reach the given joint angles
        :param speed: Set the fraction of the maximum speed used to reach the target position.
        :param stream_stiffness: Control the stiffness of the robot when streaming its joint positions.
        Note: Use stiffness, not stream_stiffness,  to control the stiffness of the robot when consuming a stream of
        joint postions.
        :param use_sensors: If true, sensor angles will be returned, otherwise command angles are used.
        :param samples_per_second: How many times per second the joint positions are sampled.
        """
        SICConfMessage.__init__(self)
        self.stiffness = stiffness
        self.speed = speed
        self.stream_stiffness = stream_stiffness
        self.use_sensors = use_sensors
        self.samples_per_second = samples_per_second


class PepperMotionStreamerService(SICComponent, NaoqiMotionTools):
    def __init__(self, *args, **kwargs):
        SICComponent.__init__(self, *args, **kwargs)

        self.session = qi.Session()
        self.session.connect("tcp://127.0.0.1:9559")

        NaoqiMotionTools.__init__(self, qi_session=self.session)

        self.motion = self.session.service("ALMotion")

        self.stiffness = 0
        self.samples_per_second = self.params.samples_per_second

        self.do_streaming = threading.Event()

        # A list of joint names (not chains)
        self.joints = self.generate_joint_list(["Body"])

        self.stream_thread = threading.Thread(target=self.stream_motion)
        self.stream_thread.name = self.get_component_name()
        self.stream_thread.start()

    @staticmethod
    def get_conf():
        return PepperMotionStreamerConf()

    @staticmethod
    def get_inputs():
        return [PepperMotionStream, StartStreaming, StopStreaming]

    def on_request(self, request):
        if request == StartStreaming:
            self.joints = self.generate_joint_list(request.joints)
            self.do_streaming.set()
            return SICMessage()

        if request == StopStreaming:
            self.do_streaming.clear()
            return SICMessage()

    def on_message(self, message):
        """
        Move the joints and base of the robot according to PepperMotionStream message
        """

        if self.stiffness != self.params.stiffness:
            self.motion.setStiffnesses(self.joints, self.params.stiffness)
            self.stiffness = self.params.stiffness

        # ? Will this happen one at a time or in parallel?
        # move the joints
        self.motion.setAngles(message.joints, message.angles, self.params.speed)

        # also move the base of the robot
        x, y, theta = message.velocity
        self.motion.move(x, y, theta)

    @staticmethod
    def get_output():
        return PepperMotionStream

    def stream_motion(self):
        # Set the stiffness value of a list of joint chain.
        # For Nao joint chains are: Head, RArm, LArm, RLeg, LLeg
        try:

            while not self._stop_event.is_set():

                # check both do_streaming and _stop_event periodically
                self.do_streaming.wait(1)
                if not self.do_streaming.is_set():
                    continue

                if self.stiffness != 0:
                    self.motion.setStiffnesses(self.joints, 0.0)
                    self.stiffness = 0

                angles = self.motion.getAngles(
                    self.joints, self.params.use_sensors
                )  # use_sensors=False

                velocity = self.motion.getRobotVelocity()
                
                self.output_message(PepperMotionStream(self.joints, angles, velocity))

                time.sleep(1 / float(self.samples_per_second))
        except Exception as e:
            self.logger.exception(e)
            self.stop()


class PepperMotionStreamer(SICConnector):
    component_class = PepperMotionStreamerService


if __name__ == "__main__":
    SICComponentManager([PepperMotionStreamerService])
