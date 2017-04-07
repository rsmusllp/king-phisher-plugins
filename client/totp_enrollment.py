import io
import os

import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

from gi.repository import Gtk
from gi.repository import GdkPixbuf
import pyotp

try:
	import qrcode
except ImportError:
	has_qrcode = False
else:
	has_qrcode = True

try:
	import PIL
except ImportError:
	has_pillow = False
else:
	has_pillow = True

gtk_builder_file = os.path.splitext(__file__)[0] + '.ui'

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'TOTP Self Enrollment'
	description = """
	This plugin allows users to manage the two factor authentication settings
	on their account. This includes setting a new and removing an existing TOTP
	secret. The two factor authentication used by King Phisher is compatible
	with free mobile applications such as Google Authenticator.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.7.0b2'
	req_packages = {
		'qrcode': has_qrcode,
		'Pillow': has_pil
	}
	def initialize(self):
		if not os.access(gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"The GTK Builder data file ({0}) is not available.".format(os.path.basename(gtk_builder_file))
			)
			return False
		self.menu_items = {}
		self.add_submenu('Tools > TOTP Self Enrollment')
		self.menu_items['setup'] = self.add_menu_item('Tools > TOTP Self Enrollment > Setup', self.enrollment_setup)
		self.menu_items['remove'] = self.add_menu_item('Tools > TOTP Self Enrollment > Remove', self.enrollment_remove)
		return True

	def check_totp(self, _, window, entry, new_otp, this_user):
		if not new_otp.verify(entry.get_text().strip()):
			gui_utilities.show_dialog_warning(
				'Incorrect TOTP',
				self.application.get_active_window(),
				'The specified TOTP code is invalid. Make sure your time\n'\
				+ 'is correct, rescan the QR code and try again.'
			)
			return
		this_user.otp_secret = new_otp.secret
		this_user.commit()
		gui_utilities.show_dialog_info(
			'TOTP Enrollment',
			self.application.get_active_window(),
			'Successfully set the TOTP secret. Your account is now enrolled\n'\
			+ 'in two factor authentication. You will be prompted to enter the\n'
			+ 'value the next time you login.'
		)
		window.destroy()

	def enrollment_remove(self, _):
		rpc = self.application.rpc
		this_user = rpc.remote_table_row('users', rpc.username)
		if this_user.otp_secret is None:
			gui_utilities.show_dialog_info(
				'Not Enrolled',
				self.application.get_active_window(),
				'This account is not currently enrolled in two factor\n'\
				+ 'authentication. There are no changes to make.'
			)
			return
		remove = gui_utilities.show_dialog_yes_no(
			'Already Enrolled',
			self.application.get_active_window(),
			'Are you sure you want to unenroll in TOTP? This will remove\n'\
			+ 'two factor authentication on your account.'
		)
		if not remove:
			return
		this_user.otp_secret = None
		this_user.commit()
		gui_utilities.show_dialog_info(
			'TOTP Unenrollment',
			self.application.get_active_window(),
			'Successfully removed the TOTP secret. Your account is now unenrolled\n'\
			+ 'in two factor authentication. You will no longer be prompted to enter\n'\
			+ 'the value when you login.'
		)

	def enrollment_setup(self, _):
		rpc = self.application.rpc
		this_user = rpc.remote_table_row('users', rpc.username)
		if this_user.otp_secret is not None:
			reset = gui_utilities.show_dialog_yes_no(
				'Already Enrolled',
				self.application.get_active_window(),
				'This account is already enrolled in TOTP,\nreset the existing TOTP token?'
			)
			if not reset:
				return
		new_otp = pyotp.TOTP(pyotp.random_base32())
		profisoning_uri = new_otp.provisioning_uri(rpc.username + '@' + rpc.host) + '&issuer=King%20Phisher'
		bytes_io = io.BytesIO()
		qrcode_ = qrcode.make(profisoning_uri).get_image()
		qrcode_.save(bytes_io, 'PNG')
		pixbuf_loader = GdkPixbuf.PixbufLoader.new()
		pixbuf_loader.write(bytes_io.getvalue())
		pixbuf_loader.close()
		pixbuf = pixbuf_loader.get_pixbuf()

		self.logger.debug('loading gtk builder file from: ' + gtk_builder_file)
		builder = Gtk.Builder()
		builder.add_from_file(gtk_builder_file)
		window = builder.get_object('TOTPEnrollment.window')
		window.set_transient_for(self.application.get_active_window())

		self.application.add_window(window)

		image = builder.get_object('TOTPEnrollment.image_qrcode')
		image.set_from_pixbuf(pixbuf)

		button_check = builder.get_object('TOTPEnrollment.button_check')
		entry_totp = builder.get_object('TOTPEnrollment.entry_totp')
		button_check.connect('clicked', self.check_totp, window, entry_totp, new_otp, this_user)
		entry_totp.connect('activate', self.check_totp, window, entry_totp, new_otp, this_user)

		window.show_all()
